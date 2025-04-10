import tabula
import pandas as pd
import os

pdf_path = "plans/workspace/活亮人生醫療保障系列附加保障ManuShine(122024).pdf"
output_dir = "plans/workspace/tables"
os.makedirs(output_dir, exist_ok=True)

# Read all tables from the PDF
tables = tabula.read_pdf(
    pdf_path,
    pages='all',
    multiple_tables=True,
    pandas_options={'header': None}
)

for i, table in enumerate(tables, start=1):
    # Skip the first row (assuming it's a header)
    if not table.empty:
        table_data = table.iloc[1:].reset_index(drop=True)
    else:
        table_data = table.copy()
    
    processed_rows = []
    for _, row in table_data.iterrows():
        processed_cells = []
        for cell in row:
            cell_str = str(cell)
            
            # Remove commas for currency values
            cell_str = cell_str.replace(',', '')
            
            # Split into parts by spaces and process
            parts = cell_str.split()
            for part in parts:
                # Try to convert to numeric if possible
                try:
                    # Remove any remaining non-numeric characters except minus
                    numeric_str = ''.join([c for c in part if c.isdigit() or c == '-'])
                    if numeric_str:
                        processed_part = int(numeric_str)
                    else:
                        processed_part = part
                except:
                    processed_part = part
                processed_cells.append(processed_part)
        
        processed_rows.append(processed_cells)
    
    # Create DataFrame and save as Excel
    if processed_rows:
        max_cols = max(len(row) for row in processed_rows)
        processed_rows = [row + [''] * (max_cols - len(row)) for row in processed_rows]
        output_path = os.path.join(output_dir, f"table{i}.xlsx")
        
        # Create DataFrame with proper typing
        df = pd.DataFrame(processed_rows)
        
        # Convert numeric columns to proper type
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='ignore')
        
        df.to_excel(
            output_path,
            index=False,
            header=False,
            engine='openpyxl'
        )
        print(f"Saved table {i} to {output_path}")
    else:
        print(f"Table {i} was empty and not saved")