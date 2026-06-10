"""
Run this ONCE on your own machine (not GitHub Actions / server):
    pip install instagrapi
    python gen_instagram_session.py

It will print a JSON blob — copy it and add it as a GitHub secret
named  INSTAGRAM_SESSION
"""
import json
from instagrapi import Client

username = input("Instagram username: ").strip()
password = input("Instagram password: ").strip()

cl = Client()
cl.delay_range = [2, 5]

print("\nLogging in...")
cl.login(username, password)

session = json.dumps(cl.get_settings())

print("\n" + "=" * 60)
print("SUCCESS — copy everything below this line as your")
print("INSTAGRAM_SESSION  GitHub secret:")
print("=" * 60)
print(session)
print("=" * 60)
