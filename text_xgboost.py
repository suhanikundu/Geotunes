import joblib
import pandas as pd

model = joblib.load("xgboost_vibe_model.pkl")
encoder = joblib.load("vibe_label_encoder.pkl")

sample = pd.DataFrame([{
    "latitude": 27.0392,
    "longitude": 88.2639,
    "elevation": 2100,
    "weather": "clear",
    "time_of_day": "afternoon",
    "population": 170000,
    "cultural_aspect": "nature-based",
    "language": "Hindi"
}])

pred = model.predict(sample)

print("Encoded prediction:", pred)

vibe = encoder.inverse_transform(pred)

print("Predicted vibe:", vibe[0])