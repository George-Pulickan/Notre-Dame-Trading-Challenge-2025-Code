import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.api import VAR
import seaborn as sns

# -------------------------
# 1. Load CSV
# -------------------------
df = pd.read_csv("prices.csv") 
df.columns = ["time", "gold", "green"]

# Ensure time is sorted
df = df.sort_values("time")

# -------------------------
# 2. Compute returns & features
# -------------------------
df["gold_return"] = df["gold"].pct_change()
df["green_return"] = df["green"].pct_change()

df["gold_diff"] = df["gold"].diff()
df["green_diff"] = df["green"].diff()

# Drop first NA row
df = df.dropna()

# -------------------------
# 3. Basic analysis
# -------------------------
print("\n--- Correlation Matrix ---")
print(df[["gold", "green", "gold_return", "green_return"]].corr())

# Plot prices
plt.figure(figsize=(10,5))
plt.plot(df["time"], df["gold"], label="Gold")
plt.plot(df["time"], df["green"], label="Green")
plt.title("Gold & Green Prices")
plt.legend()
plt.show()

# -------------------------
# 4. Stationarity check (ADF)
# -------------------------
def adf_test(series, title=""):
    result = adfuller(series)
    print(f"\nADF test for {title}")
    print(f"ADF Statistic: {result[0]}")
    print(f"p-value: {result[1]}")

adf_test(df["gold"], "gold")
adf_test(df["green"], "green")

# -------------------------
# 5. Fit VAR model
# -------------------------
model_data = df[["gold", "green"]]

# Select best lag
model = VAR(model_data)
lag = model.select_order(maxlags=5).selected_orders['aic']
print(f"\nBest lag based on AIC: {lag}")

# Fit model
results = model.fit(lag)
print(results.summary())

# -------------------------
# 6. Forecast 10 future steps (5 minutes)
# -------------------------
steps = 10
forecast = results.forecast(model_data.values[-lag:], steps=steps)
forecast_df = pd.DataFrame(forecast, columns=["gold_forecast", "green_forecast"])
print("\n--- 10-Step Forecast ---")
print(forecast_df)

# -------------------------
# 7. Plot forecasts
# -------------------------
plt.figure(figsize=(10,5))
plt.plot(range(len(df)), df["gold"], label="Gold")
plt.plot(range(len(df)), df["green"], label="Green")
plt.plot(range(len(df), len(df)+steps), forecast_df["gold_forecast"], '--', label="Gold Forecast")
plt.plot(range(len(df), len(df)+steps), forecast_df["green_forecast"], '--', label="Green Forecast")
plt.title("Actual vs Forecast - VAR Model")
plt.legend()
plt.show()

