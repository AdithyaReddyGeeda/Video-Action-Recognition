#!/usr/bin/env python3
"""
Streamlit UI for Video Action Recognition.
Run with: streamlit run streamlit_app.py
"""

import os
import tempfile
import streamlit as st
from predict_single_video import (
    load_model,
    load_video_frames,
    preprocess_frames,
    predict_video,
    VIDEO_SIZE,
    NUM_FRAMES,
    DEVICE,
)

# Paths relative to this script's directory (for Streamlit Cloud / any cwd)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(SCRIPT_DIR, "best_model.pth")
DEFAULT_LABEL_ENCODER_PATH = os.path.join(SCRIPT_DIR, "label_encoder.pkl")


@st.cache_resource
def get_model_and_encoder(model_path, label_encoder_path):
    """Load model and label encoder once and cache."""
    import pickle
    with open(label_encoder_path, "rb") as f:
        label_encoder = pickle.load(f)
    num_classes = len(label_encoder.classes_)
    model = load_model(model_path, num_classes, DEVICE)
    return model, label_encoder


def run_prediction(video_path, model, label_encoder):
    """Run prediction and return result dict."""
    return predict_video(model, video_path, label_encoder, DEVICE)


st.set_page_config(
    page_title="Video Action Recognition",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 Video Action Recognition")
st.markdown("Upload a video to classify the action using a CNN+LSTM / R3D-18 model.")

# Sidebar: model paths (optional, for advanced use)
with st.sidebar:
    st.header("Settings")
    model_path = st.text_input("Model path", value=DEFAULT_MODEL_PATH)
    label_encoder_path = st.text_input("Label encoder path", value=DEFAULT_LABEL_ENCODER_PATH)
    if not os.path.isfile(model_path):
        st.error(f"Model file not found: {model_path}")
    if not os.path.isfile(label_encoder_path):
        st.error(f"Label encoder not found: {label_encoder_path}")

# Main area: upload and predict
uploaded_file = st.file_uploader(
    "Choose a video file",
    type=["mp4", "avi", "mov", "mkv", "webm"],
    help="Supported: MP4, AVI, MOV, MKV, WebM",
)

if uploaded_file is not None:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Preview")
        # Save to temp file for preview and prediction
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
            tmp.write(uploaded_file.getvalue())
            video_path = tmp.name
        st.video(uploaded_file)

    with col2:
        st.subheader("Prediction")
        if os.path.isfile(model_path) and os.path.isfile(label_encoder_path):
            if st.button("Run prediction", type="primary"):
                with st.spinner("Loading model and predicting..."):
                    try:
                        model, label_encoder = get_model_and_encoder(model_path, label_encoder_path)
                        result = run_prediction(video_path, model, label_encoder)
                    except Exception as e:
                        st.error(f"Prediction failed: {e}")
                        result = None
                if result and "error" not in result:
                    st.success(f"**Predicted action:** {result['predictedAction']}")
                    st.metric("Confidence", f"{result['confidence'] * 100:.1f}%")
                    st.markdown("**Top 5 predictions**")
                    for i, p in enumerate(result["topPredictions"], 1):
                        st.write(f"{i}. **{p['action']}** — {p['score']*100:.1f}%")
                        st.progress(float(p["score"]))
                elif result and "error" in result:
                    st.error(result["error"])
        else:
            st.warning("Set valid model and label encoder paths in the sidebar.")

    # Clean up temp file when session ends (Streamlit may reuse; delete on next run is acceptable)
    try:
        os.unlink(video_path)
    except OSError:
        pass
else:
    st.info("👆 Upload a video to get started.")
