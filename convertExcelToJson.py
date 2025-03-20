import pandas as pd
import json
import numpy as np  # Needed for type checking

# Load the Excel file
file_path = 'plans/2025/manulife/tables/Smart_2025.xlsx'
df = pd.read_excel(file_path)

# Initialize the JSON structure
json_data = {}

# Process each deductible column
for column in df.columns:
    if column == 'Age':
        continue
    
    # Handle deductible key (numeric or string)
    if isinstance(column, str) and ' ' in column:
        deductible = column.split()[0]
    else:
        deductible = str(column)
    
    json_data[deductible] = {}
    
    # Populate age-value pairs
    for _, row in df.iterrows():
        age = str(row['Age'])
        
        # Convert numpy types to native Python types
        value = row[column]
        if isinstance(value, np.generic):
            value = value.item()  # Convert numpy type to Python type
        
        json_data[deductible][age] = value

# Save to JSON
output_path = 'Smart_2025.json'
with open(output_path, 'w') as f:
    json.dump(json_data, f, indent=2)

print(f"JSON saved to {output_path}")