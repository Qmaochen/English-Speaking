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

# --- 設定區 ---
DEFAULT_API_KEY = "" 
EXCEL_FILE = "Questions.xlsx"
WEAK_FILE = "Weak_Questions.csv" # 錯題本檔案

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

def load_questions(source="excel"):
    """讀取題目：可以是 Excel 或 錯題本 CSV"""
    file_path = EXCEL_FILE if source == "excel" else WEAK_FILE
    try:
        if source == "excel":
            df = pd.read_excel(file_path)
            col_name = 'Question'
        else:
            # 如果錯題本不存在，回傳空清單
            if not os.path.exists(file_path):
                return []
            df = pd.read_csv(file_path)
            col_name = 'Question'
            
        if col_name in df.columns:
            return df[col_name].dropna().astype(str).tolist()
        return []
    except:
        return []

def save_weak_question(question):
    """將低分題目存入 CSV"""
    if not os.path.exists(WEAK_FILE):
        df = pd.DataFrame({"Question": [question]})
        df.to_csv(WEAK_FILE, index=False)
    else:
        df = pd.read_csv(WEAK_FILE)
        if question not in df['Question'].values:
            new_row = pd.DataFrame({"Question": [question]})
            df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(WEAK_FILE, index=False)

def transcribe_audio(audio_bytes):
    r = sr.Recognizer()
    try:
        with sr.AudioFile(BytesIO(audio_bytes)) as source:
            audio_data = r.record(source)
            # Google 的辨識結果通常沒有標點，但沒關係，LLM 看得懂
            text = r.recognize_google(audio_data, language='en-US')
            return text
    except:
        return None

def get_ai_feedback(api_key, question, user_text):
    try:
        client = Groq(api_key=api_key)
        
        # [修改 1] System Prompt: 角色改為友善家教，而非嚴格考官
        system_prompt = """
        Act as a helpful, supportive English speaking tutor. 
        The user is practicing for casual conversation or IELTS Speaking Part 1.
        
        IMPORTANT: You cannot hear the audio. You can only see the transcript.
        Therefore, instead of "Pronunciation", evaluate "Clarity". 
        
        If the transcript is perfectly coherent, give a high Clarity score (it means the speech-to-text engine understood the user well).
        If the transcript has nonsense words or phonetic mix-ups (e.g., "sheep" instead of "ship"), lower the Clarity score.
        
        Your Goals:
        1. Rate leniently. Focus on communication intelligibility.
        2. In "Better Expression", DO NOT rewrite the whole paragraph. Keep the user's style. Just fix grammar.
        """

        # [修改 2] User Prompt: 調整指令
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
        (Give 2-3 brief, encouraging bullet points. If text looks wrong, ask if they meant a different word.)

        ### 💡 Better Expression
        (Modify the user's sentence MINIMALLY. Just fix grammar/prepositions. Add punctuation.)

        ### 🔧 Advice (Traditional Chinese)
        (One simple, actionable tip for next time)
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

def parse_scores(text):
    scores = {"Fluency": 0, "Vocabulary": 0, "Grammar": 0, "Clarity": 0}
    try:
        pattern = r"(\w+):\s*(\d+(\.\d+)?)" # 支援小數點
        matches = re.findall(pattern, text)
        for key, value, _ in matches:
            if key in scores:
                scores[key] = float(value)
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

st.set_page_config(page_title="Speaking Pro (Tutor Mode)", page_icon="⚡", layout="centered")
load_custom_css()

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712009.png", width=80)
    st.title("Settings")
    api_key_input = st.text_input("🔑 Groq API Key", value=DEFAULT_API_KEY, type="password")
    
    st.divider()
    st.write("📚 **Question Source**")
    
    # [修改 3] 錯題本與題庫切換功能
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
                st.toast("No weak questions saved yet!", icon="⚠️")
            else:
                st.session_state.questions_list = qs
                st.session_state.mode = "Weak Review"
                st.rerun()

    current_mode = st.session_state.get("mode", "Normal")
    st.caption(f"Current Mode: {current_mode}")

# 初始化
if "questions_list" not in st.session_state:
    st.session_state.questions_list = load_questions("excel")
if "current_question" not in st.session_state:
    st.session_state.current_question = random.choice(st.session_state.questions_list) if st.session_state.questions_list else "No Question"
if "transcript" not in st.session_state:
    st.session_state.transcript = ""
if "feedback" not in st.session_state:
    st.session_state.feedback = ""

# --- UI 佈局 ---

st.title("⚡ AI Speaking Tutor")
st.markdown("Practice comfortably. I'll fix your grammar gently.")

# 1. 題目卡片
st.markdown(f"""
<div class="question-card">
    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">CURRENT TOPIC ({st.session_state.get('mode', 'Normal')})</div>
    <div class="question-text">{st.session_state.current_question}</div>
</div>
""", unsafe_allow_html=True)

# 2. 操作按鈕區
col1, col2, col3 = st.columns([1, 2, 1], vertical_alignment="center")

with col1:
    if st.button("🎲 Skip Topic", use_container_width=True):
        if st.session_state.questions_list:
            st.session_state.current_question = random.choice(st.session_state.questions_list)
            st.session_state.transcript = ""
            st.session_state.feedback = ""
            st.rerun()

with col2:
    audio_blob = mic_recorder(start_prompt="🔴 Record", stop_prompt="⏹️ Stop", key='recorder', format="wav")

with col3:
    pass

# 3. 處理與顯示
if audio_blob:
    # [修改 4] 顯示錄音回放
    st.audio(audio_blob['bytes'], format='audio/wav')
    
    with st.spinner("⚡ Tutor is listening..."):
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
    
    # [修改 5] 自動儲存低分題目邏輯
    avg_score = sum(scores.values()) / 4 if scores else 0
    if avg_score > 0 and avg_score < 6.0: # 如果平均分低於 6 分
        save_weak_question(st.session_state.current_question)
        st.toast(f"Low score ({avg_score}). Saved to Weak Questions! ❤️", icon="💾")
    
    st.subheader("📊 Performance Score")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Fluency", f"{scores.get('Fluency', '-')}", border=True)
    m2.metric("Vocab", f"{scores.get('Vocabulary', '-')}", border=True)
    m3.metric("Grammar", f"{scores.get('Grammar', '-')}", border=True)
    m4.metric("Clarity", f"{scores.get('Clarity', '-')}", border=True)

    st.markdown("---")
    
    tab1, tab2, tab3 = st.tabs(["📝 Feedback", "💡 Better Expression", "🔧 Advice (中文)"])
    
    raw_text = st.session_state.feedback
    
    try:
        detailed_part = raw_text.split("### 📝 Feedback")[1].split("### 💡 Better Expression")[0]
        better_part = raw_text.split("### 💡 Better Expression")[1].split("### 🔧 Advice")[0]
        advice_part = raw_text.split("### 🔧 Advice (Traditional Chinese)")[1]
    except:
        detailed_part = raw_text
        better_part = "Parsing error"
        advice_part = "Check details."

    with tab1:
        st.markdown(detailed_part)
    
    with tab2:
        st.success(better_part)
        clean_better = better_part.replace("*", "").strip()
        if len(clean_better) > 5 and "Parsing error" not in clean_better:
            if st.button("🔊 Listen to Fix"):
                play_tts(clean_better)
            
    with tab3:
        st.info(advice_part)