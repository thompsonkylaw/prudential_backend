import json
import os

def get_value_from_json(json_file):
    # Load the JSON data
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{json_file}' not found.")
        return

    while True:
        print("\nEnter 'quit' to exit")
        
        age = input("Enter age: ").strip()
        
        if age.lower() == 'quit':
            break
        
        deductible = input("Enter deductible value: ").strip()
        
        if deductible.lower() == 'quit':
            break
            
        

        # Check if deductible exists
        if deductible not in data:
            print(f"Error: Deductible '{deductible}' not found in data.")
            continue
            
        # Check if age exists for the deductible
        if age not in data[deductible]:
            print(f"Error: Age '{age}' not found for deductible '{deductible}'.")
            continue
            
        # Get and display the value
        value = data[deductible][age]
        print(f"Value for age {age} and deductible {deductible}: {value}")

if __name__ == "__main__":
    json_file = os.path.join("plans", "2025", "manulife", "Smart_2025.json")
    get_value_from_json(json_file)