import streamlit as st
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder
from io import BytesIO
import edge_tts
import asyncio
import os
import random
import pandas as pd
from groq import Groq # 👈 改用 Groq
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

# 👇 [重點修改] 這裡改成呼叫 Groq API
def get_ai_feedback(api_key, question, user_text):
    try:
        client = Groq(api_key=api_key)
        
        # System Prompt: 設定 AI 的角色
        system_prompt = """
        Act as a strict IELTS speaking examiner.
        Evaluate the user's answer based on 4 criteria (0-100).
        Provide feedback in the exact requested format.
        """

        # User Prompt: 傳入題目與回答
        user_prompt = f"""
        Topic: "{question}"
        User Answer: "{user_text}"
        
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

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", # 👈 使用 Groq 上強大的 Llama 3.3 模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3, # 降低隨機性，讓格式更穩定
            max_tokens=1024
        )
        
        return completion.choices[0].message.content

    except Exception as e:
        return f"⚠️ Groq API Error: {e}"

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

st.set_page_config(page_title="Speaking Pro (Groq)", page_icon="⚡", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    # 提示使用者輸入 Groq Key
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password", help="Get it from console.groq.com")
    
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

st.title("⚡ AI Speaking Coach")
st.markdown("Powered by **Groq Llama-3** for ultra-fast feedback.")

# 1. 題目卡片
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">CURRENT TOPIC</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# 2. 操作按鈕區
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")

with col1:
    if st.button("🎲 Skip Topic", use_container_width=True):
        st.session_state.current_question = random.choice(st.session_state.questions_list)
        st.session_state.transcript = ""
        st.session_state.feedback = ""
        st.rerun()

with col2:
    # 這裡保留了 format="wav" 的修正，確保錄音正常
    audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

with col3:
    pass

# 3. 處理與顯示
if audio_blob:
    with st.spinner("⚡ Thinking at light speed..."): # 改了提示文字，強調 Groq 的速度
        transcript = transcribe_audio(audio_blob['bytes'])
        if transcript:
            st.session_state.transcript = transcript
            if api_key_input:
                feedback = get_ai_feedback(api_key_input, st.session_state.current_question, transcript)
                st.session_state.feedback = feedback
            else:
                st.error("Please enter Groq API Key")
        else:
            st.warning("No speech detected. (Try speaking louder)")

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
    
    # 簡單的解析容錯
    try:
        detailed_part = raw_text.split("### 📝 Detailed Feedback")[1].split("### 💡 Better Expression")[0]
        better_part = raw_text.split("### 💡 Better Expression")[1].split("### 🔧 Advice")[0]
        advice_part = raw_text.split("### 🔧 Advice (Traditional Chinese)")[1]
    except:
        # 如果 Llama 輸出的格式稍微跑掉，就直接顯示原始全文，避免報錯
        detailed_part = raw_text
        better_part = "Content format parsing failed, please check detailed feedback tab."
        advice_part = "Please check detailed feedback tab."

    with tab1:
        st.markdown(detailed_part)
    
    with tab2:
        st.success(better_part)
        clean_better = better_part.replace("*", "").strip()
        # 避免 TTS 讀到奇怪的錯誤訊息
        if len(clean_better) > 5 and "Parsing error" not in clean_better:
            if st.button("🔊 Listen to Native Version"):
                play_tts(clean_better)
            
    with tab3:
        st.info(advice_part)