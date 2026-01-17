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

# --- ⚙️ 設定區 ---
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
        /* Next 按鈕紅色，Retry 按鈕藍色 */
        div[data-testid="column"] button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# --- ☁️ Google Sheets 核心 ---

def get_db_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    conn = get_db_connection()
    try:
        # 🚨 關鍵修改：移除 worksheet=... 參數
        # 這樣程式就會無腦讀取「第一頁」，不管它叫 Questions 還是 Sheet1 都會成功
        df = conn.read(ttl=0)
        
        expected_cols = ["Question", "Weak_Question", "Fluency", "Vocabulary", "Grammar", "Clarity"]
        if df.empty:
            df = pd.DataFrame(columns=expected_cols)
        else:
            for col in expected_cols:
                if col not in df.columns:
                    df[col] = None
        return df
    except Exception as e:
        st.error(f"讀取錯誤: {e}")
        return pd.DataFrame()

def update_question_data(question, scores):
    conn = get_db_connection()
    try:
        # 🚨 關鍵修改：移除 worksheet=...，預設抓第一頁
        df = conn.read(ttl=0)
        df["Question"] = df["Question"].astype(str)
        
        avg_score = sum(scores.values()) / 4
        is_weak = "Yes" if avg_score < 6.0 else "No"
        
        mask = df["Question"] == question
        
        if mask.any():
            idx = df[mask].index[0]
            df.at[idx, "Weak_Question"] = is_weak
            df.at[idx, "Fluency"] = scores["Fluency"]
            df.at[idx, "Vocabulary"] = scores["Vocabulary"]
            df.at[idx, "Grammar"] = scores["Grammar"]
            df.at[idx, "Clarity"] = scores["Clarity"]
        else:
            new_row = pd.DataFrame([{
                "Question": question,
                "Weak_Question": is_weak,
                "Fluency": scores["Fluency"],
                "Vocabulary": scores["Vocabulary"],
                "Grammar": scores["Grammar"],
                "Clarity": scores["Clarity"]
            }])
            df = pd.concat([df, new_row], ignore_index=True)
        
        # 🚨 關鍵修改：這裡也不指定 worksheet，預設寫入第一頁
        conn.update(data=df)
        
        msg = "Saved! " + ("(Marked as Weak 🚩)" if is_weak == "Yes" else "(Good Job! ✅)")
        st.toast(msg, icon="💾")
        
    except Exception as e:
        st.error(f"寫入錯誤: {e}")

# --- 其他功能 ---

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
        system_prompt = """
        Act as a strict but helpful English tutor.
        First, CHECK RELEVANCE: Is the User Answer related to the Topic?
        
        IF OFF-TOPIC:
        Set all scores to 0. 
        Start feedback with "⚠️ **OFF-TOPIC WARNING**".
        
        IF RELEVANT:
        Evaluate normally based on IELTS speaking criteria.
        """
        
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
        (Bullet points. If off-topic, explain why.)
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

# --- 🔄 按鈕回調函式 ---

def reset_mic():
    st.session_state.mic_key = st.session_state.get("mic_key", 0) + 1

def next_question_callback():
    if st.session_state.questions_list:
        st.session_state.current_question = random.choice(st.session_state.questions_list)
        st.session_state.transcript = ""
        st.session_state.feedback = ""
        st.session_state.tts_audio_bytes = None
        st.session_state.scratchpad = ""
        reset_mic() 

def retry_question_callback():
    """只清除結果，保留題目"""
    st.session_state.transcript = ""
    st.session_state.feedback = ""
    st.session_state.tts_audio_bytes = None
    reset_mic() 

# --- 主程式 ---

st.set_page_config(page_title="Speaking Tutor", page_icon="☁️", layout="centered")
load_custom_css()

# Initialization
if "questions_list" not in st.session_state: st.session_state.questions_list = []
if "current_question" not in st.session_state: st.session_state.current_question = "Click a mode to start!"
if "transcript" not in st.session_state: st.session_state.transcript = ""
if "feedback" not in st.session_state: st.session_state.feedback = ""
if "tts_audio_bytes" not in st.session_state: st.session_state.tts_audio_bytes = None
if "old_scores" not in st.session_state: st.session_state.old_scores = None
if "mic_key" not in st.session_state: st.session_state.mic_key = 0 

with st.sidebar:
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    st.divider()
    
    df = load_data()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("☁️ All"):
            if not df.empty:
                st.session_state.questions_list = df['Question'].dropna().astype(str).tolist()
                st.session_state.mode = "All Questions"
                next_question_callback()
                st.rerun()
            else:
                st.error("Sheet is empty.")
                
    with col2:
        if st.button("☁️ Weak Only"):
            if not df.empty and "Weak_Question" in df.columns:
                weak_df = df[df["Weak_Question"].astype(str).str.lower() == "yes"]
                questions = weak_df["Question"].dropna().astype(str).tolist()
                
                if questions:
                    st.session_state.questions_list = questions
                    st.session_state.mode = "Weak Review"
                    next_question_callback()
                    st.rerun()
                else:
                    st.warning("No weak questions!")
            else:
                st.warning("No data.")

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
st.text_area("Scratchpad", height=68, key="scratchpad", label_visibility="collapsed", placeholder="Write notes here...")

# Buttons Layout (Retry / Next / Record)
c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="center")

with c1: 
    st.button("🔄 Retry", use_container_width=True, on_click=retry_question_callback)
    
with c2: 
    st.button("➡ Next", type="primary", use_container_width=True, on_click=next_question_callback)
    
with c3: 
    audio_blob = mic_recorder(
        start_prompt="🔴 Record", 
        stop_prompt="⏹️ Stop", 
        key=f'recorder_{st.session_state.mic_key}', 
        format="wav"
    )

# Logic
if audio_blob:
    if not st.session_state.transcript: 
        st.audio(audio_blob['bytes'], format='audio/wav')
        with st.spinner("Analyzing..."):
            transcript = transcribe_audio(audio_blob['bytes'])
            if transcript:
                st.session_state.transcript = transcript
                if api_key_input:
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
                        else: st.session_state.old_scores = None
                    except: st.session_state.old_scores = None

                    feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                    st.session_state.feedback = feedback
                    
                    parsed = parse_feedback_robust(feedback)
                    scores = parsed["scores"]
                    
                    update_question_data(st.session_state.current_question, scores)
                    
                    clean_better = parsed["better_expression"].replace("*", "").strip()
                    if len(clean_better) > 5:
                        st.session_state.tts_audio_bytes = asyncio.run(generate_audio_bytes(clean_better))
                else:
                    st.error("No API Key")
    else:
        st.info("Results for current recording (Click 'Retry' to try again)")

# Display Results
if st.session_state.transcript:
    st.divider()
    st.markdown(f"""<div class="user-answer-box"><b>🗣️ You said:</b><br>{st.session_state.transcript}</div>""", unsafe_allow_html=True)

if st.session_state.feedback:
    data = parse_feedback_robust(st.session_state.feedback)
    scores = data["scores"]
    old = st.session_state.old_scores
    
    st.subheader("📊 Results")
    
    if scores['Fluency'] == 0 and scores['Vocabulary'] == 0:
        st.error("⚠️ **Off-topic Warning**: Your answer seems unrelated to the topic.")
    
    m1, m2, m3, m4 = st.columns(4)
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