import requests

# First request to get authorization code
auth_url = "https://biz.yelp.com/oauth2/authorize"
auth_params = {
   "response_type": "code",
   "client_id": "GANk3mlkd0cbQ7fGbmYAgg",
   "scope": "leads",
   "redirect_uri": "https://zapier.com/dashboard/auth/oauth/return/App216415CLIAPI/",
   "state": "some_random_state"
}
auth_response = requests.get(auth_url, params=auth_params)
print("Auth Response:", auth_response.url)  # User needs to visit this URL and authorize

# Second request to get access token
token_url = "https://api.yelp.com/oauth2/token"
token_payload = {
   "grant_type": "authorization_code",
   "code": "rkNOA49WrnlxZiIxqU_uGZzBXYhYZ3Yx",  # Code from redirect URL after authorization
   "redirect_uri": "https://zapier.com/dashboard/auth/oauth/return/App216415CLIAPI/",
   "client_id": "GANk3mlkd0cbQ7fGbmYAgg",
   "client_secret": "G4NZeesaGwHvke077P3NtERve6NOxtEQKVPWG8zNxt8wt3ap3yxUVXW8OLaTObaf"
}
token_headers = {
   "accept": "application/json",
   "content-type": "application/x-www-form-urlencoded"
}
token_response = requests.post(token_url, data=token_payload, headers=token_headers)
print(token_response.text)