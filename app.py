import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import os
import random
import pandas as pd
from groq import Groq
import re
import json
from datetime import datetime

# --- 設定區 ---
DEFAULT_API_KEY = "" 
EXCEL_FILE = "Questions.xlsx"
WEAK_FILE = "Weak_Questions.csv"
HISTORY_FILE = "score_history.json"

# --- 💅 CSS 美化樣式 ---
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
            box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
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
        .stButton button {
            height: 44px;
        }
        /* 筆記區樣式 */
        .stTextArea textarea {
            background-color: #fff9c4; /* 淡黃色像便條紙 */
            color: #333;
        }
    </style>
    """, unsafe_allow_html=True)

# --- 核心功能函式 ---

def load_questions(source="excel"):
    file_path = EXCEL_FILE if source == "excel" else WEAK_FILE
    try:
        if source == "excel":
            df = pd.read_excel(file_path)
            col_name = 'Question'
        else:
            if not os.path.exists(file_path): return []
            df = pd.read_csv(file_path)
            col_name = 'Question'
            
        if col_name in df.columns:
            return df[col_name].dropna().astype(str).tolist()
        return []
    except:
        return []

def save_weak_question(question):
    if not os.path.exists(WEAK_FILE):
        df = pd.DataFrame({"Question": [question]})
        df.to_csv(WEAK_FILE, index=False)
    else:
        df = pd.read_csv(WEAK_FILE)
        if question not in df['Question'].values:
            new_row = pd.DataFrame({"Question": [question]})
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(WEAK_FILE, index=False)

def save_score_history(question, scores):
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass 
    
    if question not in history:
        history[question] = []
    
    record = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scores": scores
    }
    history[question].append(record)
    
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def get_previous_scores(question):
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        records = history.get(question, [])
        if len(records) >= 2:
            return records[-2]["scores"]
        else:
            return None
    except:
        return None

def transcribe_audio(audio_bytes):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(BytesIO(audio_bytes)) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language='en-US')
            return text
    except:
        return None

def get_ai_feedback(api_key, question, user_text):
    try:
        client = Groq(api_key=api_key)
        
        system_prompt = """
        Act as a helpful, supportive English speaking tutor. 
        IMPORTANT: You cannot hear the audio. You can only see the transcript.
        Evaluate "Clarity" based on how coherent the transcript is.
        
        Your Goals:
        1. Rate leniently. Focus on communication intelligibility.
        2. In "Better Expression", DO NOT rewrite the whole paragraph. Just fix grammar and vocabulary.
        3. In "Advice", provide a simple SENTENCE TEMPLATE (Pattern).
        """

        user_prompt = f"""
        Topic: "{question}"
        User Answer: "{user_text}"
        
        Please output the response in this exact format:
        
        [SCORES]
        Fluency: <score 0-10>
        Vocabulary: <score 0-10>
        Grammar: <score 0-10>
        Clarity: <score 0-10>
        [/SCORES]

        ### 📝 Feedback
        (Give 2-3 brief, encouraging bullet points.)

        ### 💡 Better Expression
        (Just fix grammar. Add punctuation.)

        ### 🔧 Advice (Template)
        (Provide a useful English sentence template/structure that the user can use to answer this question better next time.)
        """

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        
        return completion.choices[0].message.content

    except Exception as e:
        return f"⚠️ Groq API Error: {e}"

def parse_feedback_robust(text):
    result = {
        "scores": {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Clarity": 0},
        "feedback": "No feedback found.",
        "better_expression": "No better expression found.",
        "advice": "No advice found."
    }
    
    try:
        pattern = r"(\w+):\s*(\d+(\.\d+)?)"
        matches = re.findall(pattern, text)
        for key, value, _ in matches:
            if key in result["scores"]:
                result["scores"][key] = float(value)
    except:
        pass

    fb_match = re.search(r"### 📝 Feedback\s*(.*?)\s*###", text, re.DOTALL)
    if fb_match: result["feedback"] = fb_match.group(1).strip()
    
    be_match = re.search(r"### 💡 Better Expression\s*(.*?)\s*###", text, re.DOTALL)
    if be_match: result["better_expression"] = be_match.group(1).strip()
        
    ad_match = re.search(r"### 🔧 Advice.*?\)\s*(.*)", text, re.DOTALL)
    if not ad_match:
        ad_match = re.search(r"### 🔧 Advice\s*(.*)", text, re.DOTALL)
    if ad_match: result["advice"] = ad_match.group(1).strip()

    return result

# [修改] 改為生成音訊檔案並讀取為 Bytes，不直接播放
async def generate_audio_bytes(text):
    communicate = edge_tts.Communicate(text, "en-US-AndrewNeural")
    temp_filename = "temp_tts_output.mp3"
    await communicate.save(temp_filename)
    with open(temp_filename, "rb") as f:
        audio_bytes = f.read()
    return audio_bytes

# --- 頁面主程式 ---

st.set_page_config(page_title="Speaking Tutor Pro", page_icon="📈", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    
    st.divider()
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("📂 Normal"):
            st.session_state.questions_list = load_questions("excel")
            st.session_state.mode = "Normal"
            st.rerun()
    with col_s2:
        if st.button("❤️ Weak Qs"):
            qs = load_questions("weak")
            if not qs:
                st.toast("No weak questions yet!", icon="⚠️")
            else:
                st.session_state.questions_list = qs
                st.session_state.mode = "Weak Review"
                st.rerun()

    st.caption(f"Current Mode: {st.session_state.get('mode', 'Normal')}")
    
    # [需求 1] 資料下載區
    st.divider()
    st.write("💾 **Data Backup**")
    if os.path.exists(WEAK_FILE):
        with open(WEAK_FILE, "rb") as file:
            st.download_button("📥 Weak Questions (.csv)", file, "Weak_Questions.csv", "text/csv")
            
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "rb") as file:
            st.download_button("📥 Score History (.json)", file, "score_history.json", "application/json")

# 初始化 Session State
if "questions_list" not in st.session_state:
    st.session_state.questions_list = load_questions("excel")
if "current_question" not in st.session_state:
    st.session_state.current_question = random.choice(st.session_state.questions_list) if st.session_state.questions_list else "No Question"
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "feedback" not in st.session_state:
    st.session_state.feedback = ""
if "tts_audio_bytes" not in st.session_state:
    st.session_state.tts_audio_bytes = None

# --- UI ---

st.title("📈 AI Speaking Tutor")

# 1. 題目
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">CURRENT TOPIC ({st.session_state.get('mode', 'Normal')})</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# 2. [需求 2] 構思筆記區 (Scratchpad)
st.caption("📝 Scratchpad (Type your keywords here, won't be graded)")
st.text_area("Scratchpad", height=68, placeholder="Draft your ideas here...", key="scratchpad", label_visibility="collapsed")

# 3. 按鈕與錄音
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")

with col1:
    if st.button("🎲 Skip Topic", use_container_width=True):
        if st.session_state.questions_list:
            st.session_state.current_question = random.choice(st.session_state.questions_list)
            st.session_state.transcript = ""
            st.session_state.feedback = ""
            st.session_state.tts_audio_bytes = None # 清空舊的音檔
            st.session_state.scratchpad = "" # 清空筆記
            st.rerun()

with col2:
    audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

with col3:
    pass

# 4. 處理邏輯
if audio_blob:
    st.audio(audio_blob['bytes'], format='audio/wav')
    
    with st.spinner("⚡ Tutor is analyzing..."):
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
                
                # 解析並儲存
                parsed = parse_feedback_robust(feedback)
                save_score_history(st.session_state.current_question, parsed["scores"])
                
                # [需求 3] 預先生成音訊並存入 session_state
                clean_better = parsed["better_expression"].replace("*", "").strip()
                if len(clean_better) > 5:
                    audio_bytes = asyncio.run(generate_audio_bytes(clean_better))
                    st.session_state.tts_audio_bytes = audio_bytes
                else:
                    st.session_state.tts_audio_bytes = None
                
            else:
                st.error("Please enter Groq API Key")
        else:
            st.warning("No speech detected.")

# 5. 結果展示
if st.session_state.transcript:
    st.divider()
    st.markdown(f"""
    <div class="user-answer-box">
        <b>🗣️ You said:</b><br>
        {st.session_state.transcript}
    </div>
    """, unsafe_allow_html=True)

if st.session_state.feedback:
    data = parse_feedback_robust(st.session_state.feedback)
    scores = data["scores"]
    
    avg_score = sum(scores.values()) / 4 if scores else 0
    if avg_score > 0 and avg_score < 6.0:
        save_weak_question(st.session_state.current_question)
        st.toast(f"Low score ({avg_score:.1f}). Saved to Weak Questions!", icon="💾")

    prev_scores = get_previous_scores(st.session_state.current_question)
    
    st.subheader("📊 Score & Progress")
    if prev_scores:
        st.caption("Comparing with your last attempt (Green = Improved)")

    m1, m2, m3, m4 = st.columns(4)
    d_fluency = scores["Fluency"] - prev_scores["Fluency"] if prev_scores else None
    d_vocab = scores["Vocabulary"] - prev_scores["Vocabulary"] if prev_scores else None
    d_grammar = scores["Grammar"] - prev_scores["Grammar"] if prev_scores else None
    d_clarity = scores["Clarity"] - prev_scores["Clarity"] if prev_scores else None

    m1.metric("Fluency", f"{scores['Fluency']}", delta=d_fluency, border=True)
    m2.metric("Vocab", f"{scores['Vocabulary']}", delta=d_vocab, border=True)
    m3.metric("Grammar", f"{scores['Grammar']}", delta=d_grammar, border=True)
    m4.metric("Clarity", f"{scores['Clarity']}", delta=d_clarity, border=True)

    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["📝 Feedback", "💡 Better Expression", "🔧 Template"])

    with tab1:
        st.markdown(data["feedback"])
    
    with tab2:
        st.success(data["better_expression"])
        # [需求 3] 直接顯示播放器，不需要再按按鈕生成
        if st.session_state.tts_audio_bytes:
            st.audio(st.session_state.tts_audio_bytes, format="audio/mp3")
            
    with tab3:
        st.info(data["advice"])