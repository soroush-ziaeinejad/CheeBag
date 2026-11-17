import pandas as pd

df = pd.read_csv("products.csv")

# Show first 10 rows
# print(df.head(10))

# Explore dataset
print(df.shape)
print(df.columns)
print(df.info())
# def count_breadcrumbs(df):
#     return (
#         df["breadcrumbs"]
#         .dropna()
#         .str.split("->")
#         .explode()
#         .str.strip()
#         .value_counts()
#     )
#
# counts = count_breadcrumbs(df)
# print(counts)
# Filter furniture
hnk = df[df["breadcrumbs"].str.startswith("Home & Kitchen", na=False)]
# Display selected columns
print(hnk.shape)

hnk.to_csv("home&kitchen.csv")