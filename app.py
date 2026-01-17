import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import random
import pandas as pd
from groq import Groq
import re
from streamlit_gsheets import GSheetsConnection

# --- 設定區 ---
if "GROQ_API_KEY" in st.secrets:
    DEFAULT_API_KEY = st.secrets["GROQ_API_KEY"]
else:
    DEFAULT_API_KEY = ""

# --- 💅 CSS 美化 ---
def load_custom_css():
    st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .question-card {
            background-color: #f0f2f6;
            border-left: 5px solid #ff4b4b;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        .question-text {
            font-size: 24px;
            font-weight: bold;
            color: #1f1f1f;
        }
        .user-answer-box {
            background-color: #e8f4f9;
            border: 1px solid #d1e7ef;
            padding: 15px;
            border-radius: 10px;
            color: #0c5460;
            font-style: italic;
            margin-bottom: 20px;
        }
        .stButton button { height: 44px; }
    </style>
    """, unsafe_allow_html=True)

# --- ☁️ Google Sheets 核心 (單一頁面版) ---

def get_db_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """強制讀取第一頁 (Sheet1)"""
    conn = get_db_connection()
    try:
        # 不指定 worksheet，預設就是抓第一頁 (index 0)
        df = conn.read(ttl=0)
        # 確保必要的欄位存在，如果沒有就補上
        expected_cols = ["Question", "Weak_Question", "Fluency", "Vocabulary", "Grammar", "Clarity"]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None # 補空欄位
        return df
    except Exception as e:
        st.error(f"Error loading Sheet1: {e}")
        return pd.DataFrame()

def update_question_data(question, scores):
    """更新該題目的分數與 Weak 狀態"""
    conn = get_db_connection()
    try:
        df = conn.read(ttl=0)
        
        # 確保 Question 欄位是字串
        df["Question"] = df["Question"].astype(str)
        
        # 1. 計算平均分決定是否為 Weak (平均小於 6 分)
        avg_score = sum(scores.values()) / 4
        is_weak = "Yes" if avg_score < 6.0 else "No"
        
        # 2. 找到該題目的位置 (Index)
        # 這裡會回傳一個 True/False 的列表
        mask = df["Question"] == question
        
        if mask.any():
            # 如果題目已存在，直接更新那一行
            idx = df[mask].index[0]
            df.at[idx, "Weak_Question"] = is_weak
            df.at[idx, "Fluency"] = scores["Fluency"]
            df.at[idx, "Vocabulary"] = scores["Vocabulary"]
            df.at[idx, "Grammar"] = scores["Grammar"]
            df.at[idx, "Clarity"] = scores["Clarity"]
        else:
            # 如果題目不存在(極少見)，新增一行
            new_row = pd.DataFrame([{
                "Question": question,
                "Weak_Question": is_weak,
                "Fluency": scores["Fluency"],
                "Vocabulary": scores["Vocabulary"],
                "Grammar": scores["Grammar"],
                "Clarity": scores["Clarity"]
            }])
            df = pd.concat([df, new_row], ignore_index=True)
        
        # 3. 寫回 Google Sheet
        conn.update(data=df)
        
        # 顯示儲存成功訊息
        msg = "Saved! " + ("(Marked as Weak 🚩)" if is_weak == "Yes" else "(Good Job! ✅)")
        st.toast(msg, icon="💾")
        
    except Exception as e:
        st.error(f"Save Error: {e}")

# --- 其他輔助函式 ---

def transcribe_audio(audio_bytes):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(BytesIO(audio_bytes)) as source:
            audio_data = r.record(source)
            return r.recognize_google(audio_data, language='en-US')
    except: return None

def get_ai_feedback(api_key, question, user_text):
    try:
        client = Groq(api_key=api_key)
        # ... (保持原本的 Prompt)
        system_prompt = "Act as an English tutor. Evaluate Clarity based on coherence."
        user_prompt = f"""
        Topic: "{question}"
        User Answer: "{user_text}"
        
        Output exact format:
        [SCORES]
        Fluency: <0-10>
        Vocabulary: <0-10>
        Grammar: <0-10>
        Clarity: <0-10>
        [/SCORES]
        ### 📝 Feedback
        (Bullet points)
        ### 💡 Better Expression
        (Refined sentence)
        ### 🔧 Advice
        (Template)
        """
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.3, max_tokens=1024
        )
        return completion.choices[0].message.content
    except Exception as e: return f"Error: {e}"

def parse_feedback_robust(text):
    result = {"scores": {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Clarity": 0}, "feedback": "", "better_expression": "", "advice": ""}
    try:
        pattern = r"(\w+):\s*(\d+(\.\d+)?)"
        matches = re.findall(pattern, text)
        for key, value, _ in matches:
            if key in result["scores"]: result["scores"][key] = float(value)
    except: pass
    
    fb = re.search(r"### 📝 Feedback\s*(.*?)\s*###", text, re.DOTALL)
    if fb: result["feedback"] = fb.group(1).strip()
    be = re.search(r"### 💡 Better Expression\s*(.*?)\s*###", text, re.DOTALL)
    if be: result["better_expression"] = be.group(1).strip()
    ad = re.search(r"### 🔧 Advice.*?\)\s*(.*)", text, re.DOTALL)
    if not ad: ad = re.search(r"### 🔧 Advice\s*(.*)", text, re.DOTALL)
    if ad: result["advice"] = ad.group(1).strip()
    return result

async def generate_audio_bytes(text):
    communicate = edge_tts.Communicate(text, "en-US-AndrewNeural")
    temp = "temp_tts.mp3"
    await communicate.save(temp)
    with open(temp, "rb") as f: return f.read()

def skip_topic_callback():
    if st.session_state.questions_list:
        st.session_state.current_question = random.choice(st.session_state.questions_list)
        st.session_state.transcript = ""
        st.session_state.feedback = ""
        st.session_state.tts_audio_bytes = None
        st.session_state.scratchpad = ""

# --- 主程式 ---

st.set_page_config(page_title="Speaking Tutor (Single Sheet)", page_icon="☁️", layout="centered")
load_custom_css()

# Initialization
if "questions_list" not in st.session_state: st.session_state.questions_list = []
if "current_question" not in st.session_state: st.session_state.current_question = "Click a mode to start!"
if "transcript" not in st.session_state: st.session_state.transcript = ""
if "feedback" not in st.session_state: st.session_state.feedback = ""
if "tts_audio_bytes" not in st.session_state: st.session_state.tts_audio_bytes = None
# 用來暫存舊分數以便比較
if "old_scores" not in st.session_state: st.session_state.old_scores = None 

with st.sidebar:
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    st.divider()
    
    # 讀取資料
    df = load_data()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("☁️ All"):
            if not df.empty:
                st.session_state.questions_list = df['Question'].dropna().astype(str).tolist()
                st.session_state.mode = "All Questions"
                skip_topic_callback()
                st.rerun()
                
    with col2:
        if st.button("☁️ Weak Only"):
            if not df.empty:
                # 篩選 Weak_Question == "Yes" (忽略大小寫)
                if "Weak_Question" in df.columns:
                    weak_df = df[df["Weak_Question"].astype(str).str.lower() == "yes"]
                    questions = weak_df["Question"].dropna().astype(str).tolist()
                    
                    if questions:
                        st.session_state.questions_list = questions
                        st.session_state.mode = "Weak Review"
                        skip_topic_callback()
                        st.rerun()
                    else:
                        st.warning("No weak questions found!")
                else:
                    st.error("No 'Weak_Question' column.")

    st.caption(f"Mode: {st.session_state.get('mode', 'Wait')}")

st.title("☁️ AI Speaking Tutor")

# Question Card
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">TOPIC ({st.session_state.get('mode', 'Wait')})</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# Scratchpad
st.text_area("Scratchpad", height=68, key="scratchpad", label_visibility="collapsed", placeholder="Notes...")

# Buttons
c1, c2 = st.columns([1, 2], vertical_alignment="center")
with c1: st.button("🎲 Skip", use_container_width=True, on_click=skip_topic_callback)
with c2: audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

# Logic
if audio_blob:
    st.audio(audio_blob['bytes'], format='audio/wav')
    with st.spinner("Analyzing & Saving to Sheet..."):
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                # 1. 在更新之前，先抓舊分數 (為了顯示進步幅度)
                try:
                    current_q = st.session_state.current_question
                    row = df[df["Question"] == current_q]
                    if not row.empty:
                        st.session_state.old_scores = {
                            "Fluency": float(row.iloc[0].get("Fluency") or 0),
                            "Vocabulary": float(row.iloc[0].get("Vocabulary") or 0),
                            "Grammar": float(row.iloc[0].get("Grammar") or 0),
                            "Clarity": float(row.iloc[0].get("Clarity") or 0),
                        }
                    else:
                        st.session_state.old_scores = None
                except:
                    st.session_state.old_scores = None

                # 2. 取得 AI 回饋
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
                
                parsed = parse_feedback_robust(feedback)
                scores = parsed["scores"]
                
                # 3. 更新 Google Sheet (覆蓋寫入)
                update_question_data(st.session_state.current_question, scores)
                
                # 4. 生成 TTS
                clean_better = parsed["better_expression"].replace("*", "").strip()
                if len(clean_better) > 5:
                    st.session_state.tts_audio_bytes = asyncio.run(generate_audio_bytes(clean_better))
            else:
                st.error("No API Key")

# Display Results
if st.session_state.transcript:
    st.divider()
    st.markdown(f"""<div class="user-answer-box"><b>🗣️ You said:</b><br>{st.session_state.transcript}</div>""", unsafe_allow_html=True)

if st.session_state.feedback:
    data = parse_feedback_robust(st.session_state.feedback)
    scores = data["scores"]
    old = st.session_state.old_scores
    
    st.subheader("📊 Results")
    m1, m2, m3, m4 = st.columns(4)
    
    # 計算進步幅度 (這次分數 - 舊分數)
    d_fl = scores["Fluency"] - old["Fluency"] if old else None
    d_vo = scores["Vocabulary"] - old["Vocabulary"] if old else None
    d_gr = scores["Grammar"] - old["Grammar"] if old else None
    d_cl = scores["Clarity"] - old["Clarity"] if old else None
    
    m1.metric("Fluency", scores['Fluency'], delta=d_fl, border=True)
    m2.metric("Vocab", scores['Vocabulary'], delta=d_vo, border=True)
    m3.metric("Grammar", scores['Grammar'], delta=d_gr, border=True)
    m4.metric("Clarity", scores['Clarity'], delta=d_cl, border=True)
    
    t1, t2, t3 = st.tabs(["📝 Feedback", "💡 Better Expression", "🔧 Template"])
    with t1: st.markdown(data["feedback"])
    with t2: 
        st.success(data["better_expression"])
        if st.session_state.tts_audio_bytes: st.audio(st.session_state.tts_audio_bytes, format="audio/mp3")
    with t3: st.info(data["advice"])