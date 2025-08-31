import streamlit as st
import fitz  # PyMuPDF
from gtts import gTTS
import requests
import time
import os
import tempfile
from io import BytesIO
import base64

# Page configuration
st.set_page_config(
    page_title="PDF to Voice Clone",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Load external CSS
try:
    with open('style.css') as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
except FileNotFoundError:
    # Fallback inline CSS if style.css doesn't exist
    st.markdown("""
    <style>
    .app-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
    }
    .hero-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 60px 20px;
        border-radius: 20px;
        margin-bottom: 30px;
    }
    .hero-container {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 40px;
        align-items: center;
    }
    .hero-left h1 {
        font-size: 2.5rem;
        margin-bottom: 20px;
        font-weight: bold;
    }
    .hero-left p {
        font-size: 1.2rem;
        margin-bottom: 30px;
        opacity: 0.9;
    }
    .feature-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .feature-item {
        background: rgba(255,255,255,0.1);
        padding: 10px 15px;
        border-radius: 10px;
        backdrop-filter: blur(10px);
    }
    .hero-right {
        background: rgba(255,255,255,0.1);
        padding: 30px;
        border-radius: 15px;
        backdrop-filter: blur(10px);
    }
    .section-card {
        background: white;
        padding: 30px;
        border-radius: 15px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        margin: 30px 0;
    }
    .success-message {
        background: #d4edda;
        color: #155724;
        padding: 15px;
        border-radius: 10px;
        margin: 15px 0;
        border: 1px solid #c3e6cb;
    }
    .error-message {
        background: #f8d7da;
        color: #721c24;
        padding: 15px;
        border-radius: 10px;
        margin: 15px 0;
        border: 1px solid #f5c6cb;
    }
    .info-message {
        background: #cce7ff;
        color: #004085;
        padding: 15px;
        border-radius: 10px;
        margin: 15px 0;
        border: 1px solid #b8daff;
    }
    .text-preview {
        background: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        margin: 15px 0;
        border-left: 4px solid #007bff;
        font-family: monospace;
        white-space: pre-wrap;
    }
    </style>
    """, unsafe_allow_html=True)

# Initialize session state
if 'pdf_text' not in st.session_state:
    st.session_state.pdf_text = ""
if 'original_audio' not in st.session_state:
    st.session_state.original_audio = None
if 'voice_audio' not in st.session_state:
    st.session_state.voice_audio = None
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'voice_uuid' not in st.session_state:
    st.session_state.voice_uuid = ""
if 'cloned_audio' not in st.session_state:
    st.session_state.cloned_audio = None

# Functions
def extract_text_from_pdf(pdf_file):
    """Extract text from uploaded PDF file"""
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def text_to_mp3(text, lang="en"):
    """Convert text to MP3 using gTTS"""
    tts = gTTS(text=text, lang=lang)
    audio_buffer = BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer.getvalue()

def upload_audio_to_temp_host(audio_bytes):
    """Upload audio to temporary hosting service"""
    try:
        files = {'file': ('audio.wav', audio_bytes, 'audio/wav')}
        response = requests.post('https://bashupload.com', files=files)
        response.raise_for_status()
        
        response_text = response.text
        for line in response_text.splitlines():
            if line.strip().startswith('wget'):
                public_url = line.strip().split()[1]
                return public_url
        return None
    except Exception as e:
        st.error(f"Error uploading audio: {str(e)}")
        return None

def clone_voice_with_resemble(api_key, voice_uuid, project_uuid, audio_url):
    """Clone voice using Resemble AI API"""
    try:
        # Step 1: Create clip
        api_url = f"https://app.resemble.ai/api/v2/projects/{project_uuid}/clips"
        headers = {
            'Authorization': f'Token {api_key}',
            'Content-Type': 'application/json'
        }
        payload = {
            "voice_uuid": voice_uuid,
            "body": f"<resemble:convert src='{audio_url}'></resemble:convert>"
        }
        
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        if not data.get('success'):
            return None, f"API Error: {data.get('message', 'Unknown error')}"
        
        clip_uuid = data['item']['uuid']
        
        # Step 2: Poll for completion
        clip_url = f"https://app.resemble.ai/api/v2/projects/{project_uuid}/clips/{clip_uuid}"
        max_retries = 30
        
        for i in range(max_retries):
            poll_response = requests.get(clip_url, headers={'Authorization': f'Token {api_key}'})
            poll_response.raise_for_status()
            poll_data = poll_response.json()
            
            if poll_data.get('item') and poll_data['item'].get('audio_src'):
                audio_src_url = poll_data['item']['audio_src']
                
                # Step 3: Download the result
                audio_response = requests.get(audio_src_url)
                audio_response.raise_for_status()
                
                return audio_response.content, None
            
            time.sleep(2)
        
        return None, "Conversion timed out"
        
    except requests.exceptions.HTTPError as err:
        return None, f"HTTP Error: {err}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"

def get_project_uuid(api_key):
    """Get project UUID from Resemble AI"""
    try:
        headers = {'Authorization': f'Token {api_key}'}
        params = {'page': 1}
        url = 'https://app.resemble.ai/api/v2/projects'
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        if data['items']:
            return data['items'][0]['uuid'], None
        else:
            return None, "No projects found"
            
    except requests.exceptions.HTTPError as err:
        return None, f"HTTP Error: {err}"
    except Exception as e:
        return None, f"Error: {str(e)}"

# Hero Section with proper Streamlit components
st.markdown("""
<div class="hero-section">
    <div class="hero-container">
        <div class="hero-left">
            <h1>Transform PDFs into Your Voice</h1>
            <p>Upload any PDF document and convert it to speech using advanced AI voice cloning technology. Create personalized audio content with just a few clicks.</p>
            <div class="feature-list">
                <div class="feature-item">✨ Extract text from any PDF</div>
                <div class="feature-item">🎯 Convert to natural speech</div>
                <div class="feature-item">🎭 Clone with your voice</div>
            </div>
        </div>
        <div class="hero-right">
            <h3>📄 Start Your Journey</h3>
            <p>Upload your PDF document below:</p>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# PDF Upload Section
st.markdown("### 📄 Upload Your PDF")

uploaded_pdf = st.file_uploader(
    "Choose a PDF file",
    type=['pdf'],
    help="Upload a PDF document to extract text and convert to speech"
)

if uploaded_pdf is not None:
    with st.spinner("🔍 Extracting text from PDF..."):
        extracted_text = extract_text_from_pdf(uploaded_pdf)
        st.session_state.pdf_text = extracted_text
    
    st.markdown(f'<div class="success-message">✅ Successfully extracted {len(extracted_text)} characters from your PDF!</div>', unsafe_allow_html=True)

    # Preview text
    if len(extracted_text) > 300:
        preview_text = extracted_text[:300] + "..."
        st.markdown(f'<div class="text-preview"><strong>Preview:</strong><br>{preview_text}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="text-preview"><strong>Extracted Text:</strong><br>{extracted_text}</div>', unsafe_allow_html=True)

# Configuration Section
if st.session_state.pdf_text:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("## ⚙️ Configuration Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Text Length Settings")
        text_length_option = st.selectbox(
            "Choose how much text to convert:",
            ["First 500 characters (Quick)", "First 1000 characters (Medium)", "First 2000 characters (Long)", "Full text (May be slow)"],
            index=1
        )
        
        # Determine text length based on selection
        if text_length_option == "First 500 characters (Quick)":
            text_limit = 500
        elif text_length_option == "First 1000 characters (Medium)":
            text_limit = 1000
        elif text_length_option == "First 2000 characters (Long)":
            text_limit = 2000
        else:
            text_limit = len(st.session_state.pdf_text)
        
        selected_text = st.session_state.pdf_text[:text_limit] if len(st.session_state.pdf_text) > text_limit else st.session_state.pdf_text
        st.markdown(f'<div class="info-message">📊 Will convert {len(selected_text)} characters to speech</div>', unsafe_allow_html=True)

    with col2:
        st.markdown("#### Generate Speech")
        if st.button("🔊 Convert PDF to Speech", type="primary"):
            with st.spinner("🎵 Converting text to speech..."):
                audio_bytes = text_to_mp3(selected_text)
                st.session_state.original_audio = audio_bytes
            st.markdown('<div class="success-message">🎉 Your PDF has been converted to speech!</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# Voice Configuration Section
if st.session_state.original_audio:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("## 🎤 Voice Cloning Setup")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎵 Generated Speech Audio")
        st.markdown("Listen to the AI-generated speech from your PDF:")
        st.audio(st.session_state.original_audio, format='audio/mp3')
        
        # Download button for original TTS
        st.download_button(
            label="📥 Download TTS Audio",
            data=st.session_state.original_audio,
            file_name="original_tts.mp3",
            mime="audio/mp3"
        )

    with col2:
        st.markdown("#### 🎤 Upload Your Voice Sample")
        st.markdown("Upload a clear .wav file of your voice:")
        
        uploaded_voice = st.file_uploader(
            "Choose a WAV file",
            type=['wav'],
            help="Upload a clear voice sample in WAV format for voice cloning"
        )

        if uploaded_voice is not None:
            st.session_state.voice_audio = uploaded_voice.read()
            st.markdown('<div class="success-message">✅ Voice sample uploaded successfully!</div>', unsafe_allow_html=True)
            st.audio(st.session_state.voice_audio, format='audio/wav')

    # API Configuration
    st.markdown("#### 🔑 API Configuration")
    
    col3, col4 = st.columns(2)
    with col3:
        api_key = st.text_input(
            "Resemble AI API Token",
            value=st.session_state.api_key,
            type="password",
            help="Enter your Resemble AI API token"
        )
        st.session_state.api_key = api_key

    with col4:
        voice_uuid = st.text_input(
            "Voice UUID",
            value=st.session_state.voice_uuid,
            help="Enter the voice UUID from Resemble AI"
        )
        st.session_state.voice_uuid = voice_uuid

    # Clone voice button
    if st.button("🚀 Start Voice Cloning Process", type="primary"):
        if not api_key or not voice_uuid:
            st.markdown('<div class="error-message">❌ Please enter both API key and Voice UUID</div>', unsafe_allow_html=True)
        elif not st.session_state.voice_audio:
            st.markdown('<div class="error-message">❌ Please upload your voice sample first</div>', unsafe_allow_html=True)
        else:
            with st.spinner("🔄 Starting voice cloning process..."):
                # Get project UUID
                project_uuid, error = get_project_uuid(api_key)
                
                if error:
                    st.markdown(f'<div class="error-message">❌ Error getting project UUID: {error}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="info-message">📋 Project UUID: {project_uuid}</div>', unsafe_allow_html=True)
                    
                    # Upload the GENERATED TTS AUDIO
                    with st.spinner("📤 Uploading TTS audio for conversion..."):
                        public_url = upload_audio_to_temp_host(st.session_state.original_audio)
                    
                    if not public_url:
                        st.markdown('<div class="error-message">❌ Failed to upload TTS audio</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="info-message">✅ TTS audio uploaded successfully</div>', unsafe_allow_html=True)
                        
                        # Clone voice
                        with st.spinner("🎭 Converting TTS audio to your cloned voice... This may take a few minutes..."):
                            cloned_audio, error = clone_voice_with_resemble(
                                api_key, voice_uuid, project_uuid, public_url
                            )
                        
                        if error:
                            st.markdown(f'<div class="error-message">❌ Voice cloning failed: {error}</div>', unsafe_allow_html=True)
                        else:
                            st.session_state.cloned_audio = cloned_audio
                            st.markdown('<div class="success-message">🎉 Voice cloning completed successfully!</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# Results Section
if st.session_state.cloned_audio:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("## 🎯 Your Results")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎵 Original TTS Audio")
        st.markdown("The original text-to-speech audio from your PDF:")
        st.audio(st.session_state.original_audio, format='audio/mp3')
        
        st.download_button(
            label="📥 Download Original TTS",
            data=st.session_state.original_audio,
            file_name="original_tts.mp3",
            mime="audio/mp3"
        )

    with col2:
        st.markdown("#### 🎭 Your Cloned Voice")
        st.markdown("Your PDF content spoken in your cloned voice:")
        st.audio(st.session_state.cloned_audio, format='audio/wav')
        
        st.download_button(
            label="📥 Download Cloned Voice",
            data=st.session_state.cloned_audio,
            file_name="cloned_voice.wav",
            mime="audio/wav"
        )

    st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown("""
<div style="text-align: center; padding: 40px 20px; margin-top: 50px; border-top: 1px solid #eee;">
    <p style="color: #666; margin: 0;">Built with ❤️ using Streamlit and Resemble AI</p>
    <p style="color: #666; margin: 5px 0 0 0;">Transform your documents into personalized audio experiences</p>
</div>
""", unsafe_allow_html=True)

# Hide Streamlit default elements
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {visibility: hidden;}
.stDecoration {display: none;}
</style>
""", unsafe_allow_html=True)
