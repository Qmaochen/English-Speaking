import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import os
import random
import pandas as pd
import google.generativeai as genai
import re

# --- 設定區 ---
DEFAULT_API_KEY = "" 
EXCEL_FILE = "Questions.xlsx"

# --- 💅 CSS 美化樣式 ---
def load_custom_css():
    st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* 題目卡片 */
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
        
        /* 你的回答區塊 */
        .user-answer-box {
            background-color: #e8f4f9;
            border: 1px solid #d1e7ef;
            padding: 15px;
            border-radius: 10px;
            color: #0c5460;
            font-style: italic;
            margin-bottom: 20px;
        }
        
        /* 讓按鈕區塊更好看 */
        .stButton button {
            height: 44px; /* 強制設定高度以匹配錄音按鈕 */
        }
    </style>
    """, unsafe_allow_html=True)

# --- 核心功能函式 ---

def load_questions_from_excel(file_path):
    try:
        df = pd.read_excel(file_path)
        if 'Question' in df.columns:
            return df['Question'].dropna().astype(str).tolist()
        return []
    except:
        return []

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
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    Act as a strict IELTS speaking examiner.
    Topic: "{question}"
    User Answer: "{user_text}"
    
    Step 1: Evaluate based on 4 criteria (0-100).
    Step 2: Provide feedback.

    Please output the response in this exact format:
    
    [SCORES]
    Fluency: <score>
    Vocabulary: <score>
    Grammar: <score>
    Pronunciation: <score>
    [/SCORES]

    ### 📝 Detailed Feedback
    (Provide bullet points for each criteria here)

    ### 💡 Better Expression
    (One perfect native sentence)

    ### 🔧 Advice (Traditional Chinese)
    (One key tip)
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {e}"

def parse_scores(text):
    scores = {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Pronunciation": 0}
    try:
        pattern = r"(\w+):\s*(\d+)"
        matches = re.findall(pattern, text)
        for key, value in matches:
            if key in scores:
                scores[key] = int(value)
    except:
        pass
    return scores

async def _edge_tts_save(text, filename):
    communicate = edge_tts.Communicate(text, "en-US-AndrewNeural")
    await communicate.save(filename)

def play_tts(text):
    temp_file = "temp_feedback.mp3"
    asyncio.run(_edge_tts_save(text, temp_file))
    st.audio(temp_file)

# --- 頁面主程式 ---

st.set_page_config(page_title="Speaking Pro", page_icon="🎙️", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    api_key_input = st.text_input("🔑 Google API Key", value=DEFAULT_API_KEY, type="password")
    
    st.divider()
    if st.button("📂 Reload Excel Question"):
        st.session_state.questions_list = load_questions_from_excel(EXCEL_FILE)
        st.rerun()

# 初始化
if "questions_list" not in st.session_state:
    st.session_state.questions_list = load_questions_from_excel(EXCEL_FILE)
if "current_question" not in st.session_state:
    st.session_state.current_question = random.choice(st.session_state.questions_list) if st.session_state.questions_list else "No Question"
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "feedback" not in st.session_state:
    st.session_state.feedback = ""

# --- UI 佈局 ---

st.title("🎙️ AI Speaking Coach")
st.markdown("Practice your English with real-time AI feedback.")

# 1. 題目卡片
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">CURRENT TOPIC</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# 2. 操作按鈕區 [關鍵修改處]
# vertical_alignment="center" 能確保兩個元件在同一水平線上
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")

with col1:
    # use_container_width=True 讓按鈕填滿寬度，視覺上更平衡
    if st.button("🎲 Skip Topic", use_container_width=True):
        st.session_state.current_question = random.choice(st.session_state.questions_list)
        st.session_state.transcript = ""
        st.session_state.feedback = ""
        st.rerun()

with col2:
    # 這裡移除了 st.write(" ")，讓系統自動置中
    audio_blob = mic_recorder(start_prompt="🔴 Record Answer", stop_prompt="⏹️ Stop & Submit", key='recorder')

with col3:
    pass

# 3. 處理與顯示
if audio_blob:
    with st.spinner("🎧 Transcribing & Analyzing..."):
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
            else:
                st.error("Please enter API Key")
        else:
            st.warning("No speech detected.")

# 4. 結果展示
if st.session_state.transcript:
    st.divider()
    
    st.markdown(f"""
    <div class="user-answer-box">
        <b>🗣️ You said:</b><br>
        {st.session_state.transcript}
    </div>
    """, unsafe_allow_html=True)

if st.session_state.feedback:
    scores = parse_scores(st.session_state.feedback)
    
    st.subheader("📊 Performance Score")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Fluency", f"{scores.get('Fluency', '-')}", border=True)
    m2.metric("Vocab", f"{scores.get('Vocabulary', '-')}", border=True)
    m3.metric("Grammar", f"{scores.get('Grammar', '-')}", border=True)
    m4.metric("Pronun.", f"{scores.get('Pronunciation', '-')}", border=True)

    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["📝 Detailed Feedback", "💡 Better Expression", "🔧 Advice (中文)"])
    
    raw_text = st.session_state.feedback
    
    try:
        detailed_part = raw_text.split("### 📝 Detailed Feedback")[1].split("### 💡 Better Expression")[0]
        better_part = raw_text.split("### 💡 Better Expression")[1].split("### 🔧 Advice")[0]
        advice_part = raw_text.split("### 🔧 Advice (Traditional Chinese)")[1]
    except:
        detailed_part = raw_text
        better_part = "Parsing error"
        advice_part = "Parsing error"

    with tab1:
        st.markdown(detailed_part)
    
    with tab2:
        st.success(better_part)
        clean_better = better_part.replace("*", "").strip()
        if st.button("🔊 Listen to Native Version"):
            play_tts(clean_better)
            
    with tab3:
        st.info(advice_part)