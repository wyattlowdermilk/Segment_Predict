import requests

# Use the access token from Get_Code.py
ACCESS_TOKEN = "81d46eab8098ce911e5474422938dbd4a60b8c02"

headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# Example: get your athlete profile
url = "https://www.strava.com/api/v3/athlete"

response = requests.get(url, headers=headers)

print("Status Code:", response.status_code)
print("Response JSON:")
print(response.json())
