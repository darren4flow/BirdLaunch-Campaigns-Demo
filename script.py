import time
import psycopg2
import datetime
import random
import tweepy
import os
import sys
import ast
import requests
import re
from html import unescape, escape


CONSUMER_KEY = ""
CONSUMER_SECRET = ""
GENDER_API_ENDPOINT = "https://gender-api.com/v2/gender"
GENDER_API_TOKEN = ""
GENDER_API_HEADERS = {
  "Content-Type": "application/json",
  "Authorization": f"Bearer {GENDER_API_TOKEN}"
}
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
TARGET = os.environ.get("TARGET")
#KEYWORDS = ast.literal_eval(os.environ.get("KEYWORDS"))
CAMPAIGN_ID = os.environ.get("CAMPAIGN_ID")
#TEMPLATES = ast.literal_eval(os.environ.get("TEMPLATES"))
#NUM_TEMPLATES = len(TEMPLATES)

# Set up the authentication
auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)

# Create an API object
api = tweepy.API(auth, wait_on_rate_limit=True)
client = tweepy.Client(
    consumer_key=CONSUMER_KEY,
    consumer_secret=CONSUMER_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET,
    wait_on_rate_limit=True
)

MY_ID = client.get_me(user_auth=True).data.id
FOLLOWER_SOURCE_ID = str(client.get_user(username=TARGET, user_auth=True).data.id)

# --------------------------------------------------
# Production Database
conn = psycopg2.connect(
  database="",
  user="script",
  password="",
  host="",
  port="5432")
# --------------------------------------------------
#
cur = conn.cursor()

'''
Checking if the target user's DMs are open
'''
def checkDM(target_id):
  try:
    friendship = api.get_friendship(source_id=MY_ID, target_id=target_id)
    if friendship[0].can_dm:
      return True
    else:
      return False
  except:
    print("Error with checking if DMs are open")
  return False


def storeTarget(user, targets):
  # get the first name of the user
  names = user['name'].split(" ")
  firstName = names.pop(0)
  cur.execute("SELECT templates FROM campaigns WHERE campaign_id = %s",(CAMPAIGN_ID,))
  try:
    templates = cur.fetchone()[0]
    num_templates = len(templates)
  except:
    print("Could not retrieve the templates")
    sys.exit()
  message = templates[len(targets) % num_templates].format(firstName)
  targets.append((user['username'], message, user['id']))
  print("Appended {} to targets. Now has length: {}".format(user['username'], len(targets)))
  return



"""
Send messages to user
"""
def sendMessage(user, count, templates):
  # get the first name of the user
  names = user['name'].split(" ")
  firstName = names.pop(0)
  #cur.execute("SELECT templates FROM campaigns WHERE campaign_id = %s",(CAMPAIGN_ID,))

  try:
    #templates = cur.fetchone()[0]
    num_templates = len(templates)
  except:
    print("Could not retrieve the templates")
    sys.exit()

  message = templates[count % num_templates].format(firstName)
  try:
    api.send_direct_message(user['id'], message)
    print('messaged https://twitter.com/' + user['username'])
  except tweepy.TweepyException as e:
    print(e)

  return


def checkGender(user, gender):
  names = user['name'].split(" ")
  first_name = names.pop(0)

  print("Checking gender of {}".format(first_name))

  #Dealing with an edge case like Mrs. or Mr. or Dr.
  if "." in first_name:
    return False

  # Rejecting users that have more than one uppercase letter in their first name
  uppers = re.findall("[A-Z]", first_name)
  if len(uppers) > 1 or len(uppers) < 1:
    print("The first name has more than one uppercase letter or none at all.")
    return False

  response = requests.get(GENDER_API_ENDPOINT, headers=GENDER_API_HEADERS, json={"first_name": first_name})
  # Check the status code of the response
  if response.status_code == 200:
    # If the request is successful, parse the response data
    data = response.json()
    if (data['result_found']):
      if (gender == 'both' and data['probability'] >= 0.91):
        return True
      if (data['gender'] == gender and data['probability'] >= 0.91):
        return True
    else:
      print("Rejected targeting " + first_name +  " because of gender or name https://twitter.com/" + user['username'])
  else:
    # If the request is unsuccessful, print an error message
    print("Error querying Gender-API:", response.status_code)
  return False

"""
Calculate the amount of seconds until 8am EST tomorrow
"""
def seconds_till_8am():
  now = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-5)))
  midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, microsecond=0, second=0)
  one_am = midnight + datetime.timedelta(hours=8)
  return (one_am - now).seconds



def getCampaignConfig():
  cur.execute("SELECT keywords, negative_keywords, min_limit, max_limit, gender, templates FROM campaigns WHERE campaign_id = %s", (CAMPAIGN_ID,))
  campaign_record = cur.fetchone()
  return {
    'keywords': campaign_record[0],
    'negative_keywords': campaign_record[1],
    'min_limit': campaign_record[2][0],
    'max_limit': campaign_record[3][0],
    'gender': campaign_record[4],
    'templates': campaign_record[5]
  }


"""
Itereates through a user's list of followers, checks if a follower has the keywords we're looking for in their bio, checks if their DMs
are open, checks if they're the right gender, checks if they haven't already been messaged, then sends off a DM if everything
checks out
"""
def main():
  hasNextPage = True
  nextToken = None
  messages_sent = 0

  while hasNextPage:
    resp = client.get_users_followers(id=FOLLOWER_SOURCE_ID, pagination_token=nextToken, max_results=1000,user_fields=["description", "public_metrics"], user_auth=True)
    if resp and resp.meta and resp.meta['result_count'] and resp.meta['result_count'] > 0:
        if resp.data:
          for user in resp.data:
            config = getCampaignConfig()
            if (len(config['max_limit']) != 0):
              if (user['public_metrics']['followers_count'] >= int(config['max_limit'])):
                continue
            if (len(config['min_limit']) != 0):
              if (user['public_metrics']['followers_count'] <= int(config['min_limit'])):
                continue

            bio = user['description'].lower()
            # Skipping user if they have a negative keyword in their bio
            skip = False
            if (len(config['negative_keywords'][0]) != 0):
              for neg_kw in config['negative_keywords']:
                if neg_kw.lower() in bio:
                  skip = True
            if (skip):
              continue

            # Skpping user if they don't have a targeted keyword if their bio
            hasTargetKeyword = False
            if (len(config['keywords'][0]) > 0):
              for keyword in config['keywords']:
                if keyword.lower() in bio:
                  hasTargetKeyword = True
            else:
              hasTargetKeyword = True
            if (not hasTargetKeyword):
              continue
            if checkDM(user['id']):
              cur.execute("SELECT * FROM msgd_{} WHERE twitter_id='{}'".format(str(MY_ID),str(user['id'])))
              if cur.rowcount == 0:
                # Add the gender check right here
                if checkGender(user, config['gender']):
                  sendMessage(user, messages_sent, config['templates'])
                  messages_sent += 1
                  cur.execute("INSERT INTO msgd_{} (twitter_id, count) VALUES ({}, {})".format(str(MY_ID), str(user['id']), "1"))
                  conn.commit()
                  time.sleep(random.randint(120, 240))
                  if messages_sent == 200:
                    time.sleep(seconds_till_8am())
                    messages_sent = 0
        if 'next_token' in resp.meta:
          nextToken = resp.meta['next_token']
        else:
          hasNextPage = False
    else:
      hasNextPage = False
  # Update the campaign to done.
  print("Iterated through entire list of followers")
  cur.close()
  conn.close()



if __name__ == "__main__":
    main()
