import pandas as pd

path = "forecast-service/data/ames_train.csv"
df = pd.read_csv(path)
df = df.rename(columns={
    "GrLivArea": "Gr Liv Area",
    "TotalBsmtSF": "Total Bsmt SF",
    "GarageArea": "Garage Area",
    "YearBuilt": "Year Built",
    "OverallQual": "Overall Qual",
    "MSZoning": "MS Zoning",
})
df.to_csv(path, index=False)
print(df.columns.tolist())