import pandas as pd
import json
import numpy as np  # Needed for type checking

# Load the Excel file
filename ="守護一生醫療_附加保障_適用於非香港或澳門居民_2024-07-01_HKD_男_基礎"
file_path = f'plans/workspace/tables/{filename}.xlsx'
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
        age = str(int(row['Age']))
        
        # Convert numpy types to native Python types
        value = row[column]
        if isinstance(value, np.generic):
            value = value.item()  # Convert numpy type to Python type
        
        json_data[deductible][age] = value

# Save to JSON
output_path = f'plans/manulife/{filename}.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(json_data, f, indent=2, ensure_ascii=False)

print(f"JSON saved to {output_path}")