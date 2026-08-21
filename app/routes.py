from flask import render_template, flash, redirect, request, url_for
from app import app

from flask_wtf import FlaskForm
from wtforms import RadioField, SubmitField, StringField
from wtforms.validators import Optional, DataRequired, ValidationError

from flask_login import current_user, login_user, login_required, logout_user

import sqlalchemy as sa
from app import db
from app.models import User, Event, Round, Song, Match, Vote, Candidate
from app.forms import LoginForm, RegistrationForm

from datetime import datetime, timedelta
import pytz
from urllib.parse import urlsplit
import re
from markupsafe import Markup
import random
from wonderwords import RandomWord

# By default, get any rounds that ended in the last 48 hours.
def get_recent_rounds(delta = timedelta(hours=48)):
  threshold = datetime.now() - delta
  rounds = db.session.scalars(sa.select(Round).filter(threshold < Round.end_time).filter(Round.end_time < datetime.now())).all()

  recent_rounds = []
  for round in rounds:

    # Oops, crazy slow again.
    tiebreaks = needs_tiebreaker(count_votes(round.event.event_slug, round.round_slug))

    if current_user.is_authenticated:
      did_you_start, did_you_finish = did_you_vote(current_user.id, round.event.event_slug, round.round_slug)
    else:
      did_you_start = False
      did_you_finish = False

    recent_rounds.append({
      'name': f'{round.event.name} Round {round.round_slug}',
      'round_slug': round.round_slug,
      'event_slug': round.event.event_slug,
      'slug': f'{round.event.event_slug}-{round.round_slug}',
      'needs_tiebreaker': len(tiebreaks) > 0,
      'tiebreaks': tiebreaks,
      'did_you_start': did_you_start,
      'did_you_finish': did_you_finish
    })

  return recent_rounds

def get_active_rounds():
  dtnow = datetime.now()
  rounds = db.session.scalars(sa.select(Round).filter(Round.start_time < dtnow).filter(dtnow < Round.end_time)).all()

  active_rounds = []
  for round in rounds:

    if current_user.is_authenticated:
      did_you_start, did_you_finish = did_you_vote(current_user.id, round.event.event_slug, round.round_slug)
    else:
      did_you_start = False
      did_you_finish = False

    active_rounds.append({
      'name': f'{round.event.name} Round {round.round_slug}',
      'round_slug': round.round_slug,
      'event_slug': round.event.event_slug,
      'slug': f'{round.event.event_slug}-{round.round_slug}',
      'end_time': round.end_time,
      'did_you_start': did_you_start,
      'did_you_finish': did_you_finish
    })

  return active_rounds

# Get the pick statuses for a single user in a single event.
def get_pick_status(user_id, event_slug):
  event = get_event(event_slug)

  pick_status = {}

  # maybe the number of picks can be variable in the future
  # for now, hard-code 4 picks
  for pick_num in range(1, 5):
    existing_pick = get_pick(user_id, event.id, pick_num)

    if existing_pick:
      pick_status[pick_num] = existing_pick.approved
    else:
      pick_status[pick_num] = 'BLANK'

  return pick_status

# Get all the pick statuses for all users in a single event.
# Returns a dict of dicts.
def get_all_pick_statuses(event_slug):
  event = get_event(event_slug)
  pick_statuses = {}

  # Checking every user might be slow if this site ever gets big.
  # Until then, whatever.
  all_users = db.session.scalars(sa.select(User)).all()

  for user in all_users:
    user_has_picks = db.session.scalar(sa.select(Song)
      .filter(Song.user_id == user.id)
      .filter(Song.event_id == event.id))
    if user_has_picks:
      pick_statuses[user.username] = get_pick_status(user.id, event_slug)

  return pick_statuses

def get_active_nominations():

  active_nominations = []

  dtnow = datetime.now()
  events = db.session.scalars(sa.select(Event)
    .filter(Event.pick_deadline > dtnow)).all()

  for event in events:
    if current_user.is_authenticated:
      pick_status = get_pick_status(current_user.id, event.event_slug)
    else:
      pick_status = None

    active_nominations.append({
      'name': event.name,
      'event_slug': event.event_slug,
      'pick_status': pick_status,
      'pick_deadline': event.pick_deadline
    })

  return active_nominations


##################
# DATABASE UTILS #
##################

# Get a list of the specified user's Vote objects for a specific round.
def get_votes_in_round(user_id, round_id):
  return db.session.scalars(sa.select(Vote, Match)
      .filter(Vote.match_id == Match.id) # table join
      .filter(Vote.user_id == user_id) # find user's votes
      .filter(Match.round_id == round_id) # find votes in current round
    ).all()

# Get the specified user's Vote object for a specific match.
def get_vote_in_match(user_id, match_id):
  return db.session.scalar(sa.select(Vote)
    .filter(Vote.match_id == match_id) # find the specific match
    .filter(Vote.user_id == user_id) # find user's vote
  )

# Get a list of Vote objects that voted for a specific song in a specific match.
def get_votes_for_song_in_match(song_id, match_id):
  votes = db.session.scalars(sa.select(Vote)
        .where(Vote.match_id == match_id) # all votes for current match
        .where(Vote.song_id == song_id) # that voted for current song
      ).all()
  return votes

# Get the specified Round object.
def get_round(event_slug, round_slug):
  round = db.one_or_404(sa.select(Round, Event)
    .filter(Round.event_id == Event.id) # table join
    .filter(Round.round_slug == round_slug) # find specific round
    .filter(Event.event_slug == event_slug) # in specific event
    )
  return round

# Get the specified Event object.
def get_event(event_slug):
  event = db.one_or_404(sa.select(Event)
    .filter(Event.event_slug == event_slug) # in specific event
    )
  return event

# Get a list of all Match objects for a specific round.
# Return value is ordered by Match ID.
def get_matches(event_slug, round_slug):
  round = db.one_or_404(sa.select(Round, Event)
    .filter(Round.event_id == Event.id) # table join
    .filter(Round.round_slug == round_slug) # find specific round
    .filter(Event.event_slug == event_slug)) # in specific event
  matches = db.session.scalars(round.matches.select()
    .order_by(Match.id) # order by match ID
  ).all()
  return matches

# Get the Song objects for a specific match.
# Return value is ordered by Song ID.
def get_songs(match_id):
  match = db.session.scalar(sa.select(Match).filter(Match.id == match_id)) # find the Match object
  candidates = db.session.scalars(match.candidates.select().order_by(Candidate.song_id)).all() # find the Candidate objects

  songs = []
  for candidate in candidates:
    song = db.session.scalar(sa.select(Song).where(Song.id == candidate.song_id)) # match each Candidate to a Song
    songs.append(song)
  return songs

def get_match(match_id):
  match = db.session.scalar(sa.select(Match).filter(Match.id == match_id)) # find the Match object
  return match

def get_voter_username(vote):
  return db.session.scalar(sa.select(User).where(User.id == vote.user_id)).username

#################
# VOTE COUNTING #
#################

# Returns whether the user started voting in the round,
# and whether the user finished voting in the round.
def did_you_vote(user_id, event_slug, round_slug):
  round = get_round(event_slug, round_slug)
  matches = get_matches(event_slug, round_slug)
  your_votes_in_round = get_votes_in_round(user_id, round.id)
  did_you_start = len(your_votes_in_round) > 0
  did_you_finish = len(your_votes_in_round) == len(matches)
  return did_you_start, did_you_finish

# Given a match, return a list of dicts.
# Each dicts has info about who voted for that song.
def get_song_dicts(match_id):
  match = get_match(match_id)
  matches = get_matches(match.round.event.event_slug, match.round.round_slug)

  match_lst = [] # ordered by song_id, thanks to the query in get_songs

  for song_idx, song in enumerate(get_songs(match_id)):

    song_dict = {'song': song, 'tally': 0, 'voters': [], 'eliminated' : False, 'needs_tiebreaker': False}

    votes = get_votes_for_song_in_match(song.id, match_id)

    for vote in votes:

      # only log votes if you finished voting
      # or if you are tiebreaker
      # doing this in a triple-nested loop is crazy slow.
      # I should work out how to speed it up.
      did_you_vote = get_votes_in_round(vote.user_id, match.round.id)
      did_you_finish = len(did_you_vote) == len(matches)

      if did_you_finish or vote.is_tiebreaker:
        song_dict['voters'].append(get_voter_username(vote))
        song_dict['tally'] += 1

    match_lst.append(song_dict)

  return match_lst


def count_votes(event_slug, round_slug):
  round = get_round(event_slug, round_slug)
  dtnow = datetime.now()
  round_over = dtnow > round.end_time

  match_lsts = [] # ordered by match_id, thanks to the query in get_matches
  matches = get_matches(event_slug, round_slug)

  for match in matches:

    match_lst = get_song_dicts(match.id)
    match_lsts.append(match_lst)

    # eliminate the loser of this match
    if round_over:
      min_song = min(match_lst, key=lambda x : x['tally'])
      no_ties = sum(song['tally'] == min_song['tally'] for song in match_lst) == 1
      if no_ties:
        min_song['eliminated'] = True
      else:
        for song_dict in match_lst:
          if song_dict['tally'] == min_song['tally']:
            song_dict['needs_tiebreaker'] = True

  return match_lsts

# Returns a sorted list of match numbers that need tiebreaker.
# This requires match_lsts which is crazy slow.
# I should work out how to speed it up.
def needs_tiebreaker(match_lsts):
  tied_matches = set() # match nums
  for match_idx, match_lst in enumerate(match_lsts):
    match_num = match_idx + 1
    for song_dict in match_lst:
      if song_dict['needs_tiebreaker']:
        tied_matches.add(match_num)
  return sorted(list(tied_matches))

def add_vote(submission, is_tiebreaker):
  user_id = current_user.id
  for match in submission:
    if 'match' in match:
      match_id = int(re.sub(r'match', '', match))
      song = submission[match]
      song_id = int(re.search(r".*-(.*)", song).group(1))
      vote = Vote(match_id=match_id, user_id=user_id, song_id=song_id, is_tiebreaker=is_tiebreaker)
      db.session.merge(vote)
  db.session.commit()

####################
# ADVANCING ROUNDS #
####################

# Returns Song object for the highest vote-getter in the match.
def get_winning_song(match_id):
  match = get_match(match_id)

  # used later to check for complete votes only
  matches = get_matches(match.round.event.event_slug, match.round.round_slug)

  # used later to check for tiebreaker votes
  round_over = datetime.now() > get_round(match.round.event.event_slug, match.round.round_slug).end_time

  match_lst = get_song_dicts(match_id)

  # find the winner of this match
  dtnow = datetime.now()
  round_over = dtnow > match.round.end_time
  if round_over:
    max_song = max(match_lst, key=lambda x : x['tally'])
    no_ties = sum(song['tally'] == max_song['tally'] for song in match_lst) == 1
    if no_ties:
      return max_song['song']

# Attempts to populate matches in the round that has been requested.
# Checks exist so that this hopefully only happens once per round.
def populate_round(event_slug, round_slug):

  round = get_round(event_slug, round_slug)

  # Matches for the current round we are trying to populate.
  matches = get_matches(event_slug, round_slug)

  # If any current match has candidates already, do nothing.
  for match in matches:
    songs_in_match = get_songs(match.id)
    if len(songs_in_match) > 0:
      return

  # Fetch all the previous rounds that the current round depends on.
  # Each previous round is a (event_slug, round_slug) tuple.
  prev_rounds_lst = []
  for prev_round in round.prev_rounds:
    prev_rounds_lst.append((prev_round.event.event_slug, prev_round.round_slug))

  # If any previous round needs a tiebreaker, do nothing.
  for prev_event_slug, prev_round_slug in prev_rounds_lst:
    match_lsts = count_votes(prev_event_slug, prev_round_slug)
    if needs_tiebreaker(match_lsts):
      return

  # Fetch all the winners of matches in the previous rounds.
  # One winner per match.
  prev_winners = []
  for (prev_event_slug, prev_round_slug) in prev_rounds_lst:
    for prev_match in get_matches(prev_event_slug, prev_round_slug):
      prev_winners.append(get_winning_song(prev_match.id))  

  # Attempt to populate each match with a winner from our list of winners.
  # Round-robin gives each match one song, then each match a second song, and so on.
  # In theory the rounds and matches-per-round are set up so that
  # len(list of winners) is exactly equal to the number of songs needed in this round.
  # TODO: Avoid self vs self match-ups. Use a dict of some sort?
  # Theory: Using an incrementing i here instead of a seed results in March Madness.
  # Maybe? Not super sure.
  random.seed(100)
  while len(prev_winners) > 0:
    for new_match in matches:
      i = random.randint(0, len(prev_winners) - 1)
      new_song_id = prev_winners[i].id
      new_match_id = new_match.id

      new_candidate = Candidate(song_id=new_song_id, match_id=new_match_id)
      db.session.add(new_candidate)

      prev_winners.pop(i)

  db.session.commit()

# Returns a boolean that we can use to check if we should show the matches,
# or show an unreleased message.
def is_round_populated(event_slug, round_slug):

  # Matches for the current round we are trying to populate.
  matches = get_matches(event_slug, round_slug)

  # If any current match has candidates already, return True.
  for match in matches:
    songs_in_match = get_songs(match.id)
    if len(songs_in_match) > 0:
      return True

  return False


##################
# CREATING MATCH #
##################

# match numbers from https://i.imgur.com/IuiOrgC.jpeg
def create_64_bracket():
  event = Event(event_slug='fa26-music', name='2026 Fall Music Showdown',
    pick_deadline=datetime(2026, 8, 18, 15, 0))
  event = db.session.merge(event)
  db.session.commit()

  round6 = Round(event_id=event.id, round_slug='6',
    start_time=datetime(2026, 8, 28, 15, 0),
    end_time=datetime(2026, 8, 29, 15, 0),
    next_round_id=-1)
  round6 = db.session.merge(round6)
  db.session.commit()

  round5 = Round(event_id=event.id, round_slug='5',
    start_time=datetime(2026, 8, 27, 15, 0),
    end_time=datetime(2026, 8, 28, 15, 0),
    next_round_id=round6.id)
  round5 = db.session.merge(round5)
  db.session.commit()

  round4 = Round(event_id=event.id, round_slug='4',
    start_time=datetime(2026, 8, 26, 15, 0),
    end_time=datetime(2026, 8, 27, 15, 0),
    next_round_id=round5.id)
  round4 = db.session.merge(round4)
  db.session.commit()

  round3 = Round(event_id=event.id, round_slug='3',
    start_time=datetime(2026, 8, 25, 15, 0),
    end_time=datetime(2026, 8, 26, 15, 0),
    next_round_id=round4.id)
  round3 = db.session.merge(round3)
  db.session.commit()

  round2a = Round(event_id=event.id, round_slug='2A',
    start_time=datetime(2026, 8, 23, 15, 0),
    end_time=datetime(2026, 8, 24, 15, 0),
    next_round_id=round3.id)
  round2b = Round(event_id=event.id, round_slug='2B',
    start_time=datetime(2026, 8, 24, 15, 0),
    end_time=datetime(2026, 8, 25, 15, 0),
    next_round_id=round3.id)
  round2a = db.session.merge(round2a)
  round2b = db.session.merge(round2b)
  db.session.commit()

  round1a = Round(event_id=event.id, round_slug='1A',
    start_time=datetime(2026, 8, 19, 15, 0),
    end_time=datetime(2026, 8, 20, 15, 0),
    next_round_id=round2a.id)
  round1b = Round(event_id=event.id, round_slug='1B',
    start_time=datetime(2026, 8, 20, 15, 0),
    end_time=datetime(2026, 8, 21, 15, 0),
    next_round_id=round2a.id)
  round1c = Round(event_id=event.id, round_slug='1C',
    start_time=datetime(2026, 8, 21, 15, 0),
    end_time=datetime(2026, 8, 22, 15, 0),
    next_round_id=round2b.id)
  round1d = Round(event_id=event.id, round_slug='1D',
    start_time=datetime(2026, 8, 22, 15, 0),
    end_time=datetime(2026, 8, 23, 15, 0),
    next_round_id=round2b.id)
  round1a = db.session.merge(round1a)
  round1b = db.session.merge(round1b)
  round1c = db.session.merge(round1c)
  round1d = db.session.merge(round1d)
  db.session.commit()

  match63 = Match(round_id=round6.id)
  match63 = db.session.merge(match63)
  db.session.commit()

  match61 = Match(round_id=round5.id)
  match62 = Match(round_id=round5.id)
  match61 = db.session.merge(match61)
  match62 = db.session.merge(match62)
  db.session.commit()

  match57 = Match(round_id=round4.id)
  match58 = Match(round_id=round4.id)
  match59 = Match(round_id=round4.id)
  match60 = Match(round_id=round4.id)
  match57 = db.session.merge(match57)
  match58 = db.session.merge(match58)
  match59 = db.session.merge(match59)
  match60 = db.session.merge(match60)
  db.session.commit()

  match49 = Match(round_id=round3.id)
  match50 = Match(round_id=round3.id)
  match51 = Match(round_id=round3.id)
  match52 = Match(round_id=round3.id)
  match53 = Match(round_id=round3.id)
  match54 = Match(round_id=round3.id)
  match55 = Match(round_id=round3.id)
  match56 = Match(round_id=round3.id)
  match49 = db.session.merge(match49)
  match50 = db.session.merge(match50)
  match51 = db.session.merge(match51)
  match52 = db.session.merge(match52)
  match53 = db.session.merge(match53)
  match54 = db.session.merge(match54)
  match55 = db.session.merge(match55)
  match56 = db.session.merge(match56)
  db.session.commit()

  match33 = Match(round_id=round2a.id)
  match34 = Match(round_id=round2a.id)
  match35 = Match(round_id=round2a.id)
  match36 = Match(round_id=round2a.id)
  match37 = Match(round_id=round2a.id)
  match38 = Match(round_id=round2a.id)
  match39 = Match(round_id=round2a.id)
  match40 = Match(round_id=round2a.id)

  match41 = Match(round_id=round2b.id)
  match42 = Match(round_id=round2b.id)
  match43 = Match(round_id=round2b.id)
  match44 = Match(round_id=round2b.id)
  match45 = Match(round_id=round2b.id)
  match46 = Match(round_id=round2b.id)
  match47 = Match(round_id=round2b.id)
  match48 = Match(round_id=round2b.id)

  match33 = db.session.merge(match33)
  match34 = db.session.merge(match34)
  match35 = db.session.merge(match35)
  match36 = db.session.merge(match36)
  match37 = db.session.merge(match37)
  match38 = db.session.merge(match38)
  match39 = db.session.merge(match39)
  match40 = db.session.merge(match40)

  match41 = db.session.merge(match41)
  match42 = db.session.merge(match42)
  match43 = db.session.merge(match43)
  match44 = db.session.merge(match44)
  match45 = db.session.merge(match45)
  match46 = db.session.merge(match46)
  match47 = db.session.merge(match47)
  match48 = db.session.merge(match48)
  db.session.commit()

  match1 = Match(round_id=round1a.id)
  match2 = Match(round_id=round1a.id)
  match3 = Match(round_id=round1a.id)
  match4 = Match(round_id=round1a.id)
  match5 = Match(round_id=round1a.id)
  match6 = Match(round_id=round1a.id)
  match7 = Match(round_id=round1a.id)
  match8 = Match(round_id=round1a.id)

  match9 = Match(round_id=round1b.id)
  match10 = Match(round_id=round1b.id)
  match11 = Match(round_id=round1b.id)
  match12 = Match(round_id=round1b.id)
  match13 = Match(round_id=round1b.id)
  match14 = Match(round_id=round1b.id)
  match15 = Match(round_id=round1b.id)
  match16 = Match(round_id=round1b.id)

  match17 = Match(round_id=round1c.id)
  match18 = Match(round_id=round1c.id)
  match19 = Match(round_id=round1c.id)
  match20 = Match(round_id=round1c.id)
  match21 = Match(round_id=round1c.id)
  match22 = Match(round_id=round1c.id)
  match23 = Match(round_id=round1c.id)
  match24 = Match(round_id=round1c.id)

  match25 = Match(round_id=round1d.id)
  match26 = Match(round_id=round1d.id)
  match27 = Match(round_id=round1d.id)
  match28 = Match(round_id=round1d.id)
  match29 = Match(round_id=round1d.id)
  match30 = Match(round_id=round1d.id)
  match31 = Match(round_id=round1d.id)
  match32 = Match(round_id=round1d.id)

  match1 = db.session.merge(match1)
  match2 = db.session.merge(match2)
  match3 = db.session.merge(match3)
  match4 = db.session.merge(match4)
  match5 = db.session.merge(match5)
  match6 = db.session.merge(match6)
  match7 = db.session.merge(match7)
  match8 = db.session.merge(match8)

  match9 = db.session.merge(match9)
  match10 = db.session.merge(match10)
  match11 = db.session.merge(match11)
  match12 = db.session.merge(match12)
  match13 = db.session.merge(match13)
  match14 = db.session.merge(match14)
  match15 = db.session.merge(match15)
  match16 = db.session.merge(match16)

  match17 = db.session.merge(match17)
  match18 = db.session.merge(match18)
  match19 = db.session.merge(match19)
  match20 = db.session.merge(match20)
  match21 = db.session.merge(match21)
  match22 = db.session.merge(match22)
  match23 = db.session.merge(match23)
  match24 = db.session.merge(match24)

  match25 = db.session.merge(match25)
  match26 = db.session.merge(match26)
  match27 = db.session.merge(match27)
  match28 = db.session.merge(match28)
  match29 = db.session.merge(match29)
  match30 = db.session.merge(match30)
  match31 = db.session.merge(match31)
  match32 = db.session.merge(match32)

  db.session.commit()

# assuming no byes
def populate_first_round():
  event = db.session.scalar(sa.select(Event).where(Event.event_slug == 'fa26-music'))

  first_rounds = [
    get_matches('fa26-music', '1A'),
    get_matches('fa26-music', '1B'),
    get_matches('fa26-music', '1C'),
    get_matches('fa26-music', '1D')
  ]
  i = 0
  for first_round in first_rounds:
    for match in first_round:
      new_song_1 = Song(user_id=1, event_id=event.id,
        artist=f'Artist {i}', title=f'Title {i}', link=f'www{i}.example.com',
        pick_num=(i % 3) + 1, pick_time=datetime.now(), approved='APPROVED')
      i += 1
      new_song_2 = Song(user_id=1, event_id=event.id,
        artist=f'Artist {i}', title=f'Title {i}', link=f'www{i}.example.com',
        pick_num=(i % 3) + 1, pick_time=datetime.now(), approved='APPROVED')
      i += 1
      new_song_1 = db.session.merge(new_song_1)
      new_song_2 = db.session.merge(new_song_2)
      db.session.commit()

      candidate_1 = Candidate(song_id=new_song_1.id, match_id=match.id)
      candidate_2 = Candidate(song_id=new_song_2.id, match_id=match.id)
      candidate_1 = db.session.merge(candidate_1)
      candidate_2 = db.session.merge(candidate_2)
      db.session.commit()





###############
# AUTH ROUTES #
###############

@app.route('/')
def index():
  if current_user.is_authenticated:
    un = f'You are: {current_user.username}'
    if not current_user.is_verified:
      un += f' and you need to post the code "{current_user.verify_code}" on the NHC to prove it\'s really you.'
  else:
    un = 'You are: Anonymous'
  return render_template('debug.html', debug=un, 
    active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations())

@app.route('/login', methods=['GET', 'POST'])
def login():
  if current_user.is_authenticated:
    return redirect(url_for('index'))
  form = LoginForm()
  if form.validate_on_submit():
    user = db.session.scalar(
      sa.select(User).where(User.username == form.username.data))
    if user is None or not user.check_password(form.password.data):
      flash('Invalid username or password')
      return redirect(url_for('login'))
    login_user(user, remember=form.remember_me.data)
    next_page = request.args.get('next')
    if not next_page or urlsplit(next_page).netloc != '':
      next_page = url_for('index')
    return redirect(next_page)
  return render_template('login.html', title='Sign In', form=form,
    active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations())

@app.route('/logout')
def logout():
  logout_user()
  return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
  if current_user.is_authenticated:
    return redirect(url_for('index'))
  form = RegistrationForm()
  if form.validate_on_submit():
    user = User(username=form.username.data, email=form.email.data)
    user.set_password(form.password.data)
    r = RandomWord()
    user.verify_code = f'{r.word()}-{r.word()}-{r.word()}'
    user.is_verified = False
    db.session.add(user)
    db.session.commit()
    flash(f'Registered as {user.username}. To activate your account, prove it\'s you by posting the code "{user.verify_code}" on the NHC.')
    return redirect(url_for('login'))
  return render_template('register.html', title='Register', form=form,
    active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations())


###############
# VOTE ROUTES #
###############

@app.route('/vote/<event_slug>/<round_slug>/', methods=['GET', 'POST'])
@login_required
def vote(event_slug, round_slug):

  if not current_user.is_verified:
    flash(f'To activate your account, prove it\'s you by posting the code "{current_user.verify_code}" on the NHC.')
    return redirect(url_for('index'))

  # Attempt to populate before showing "unreleased" - so that when a round opens, somebody
  # can actually populate it.
  # In theory, this only does something the first time the user requests a round.
  populate_round(event_slug, round_slug)

  # Show "unreleased" if the round hasn't started yet.
  round_started = datetime.now() > get_round(event_slug, round_slug).start_time
  if not round_started or not is_round_populated(event_slug, round_slug):
    return render_template('unreleased.html', title=f'Vote in Round {round_slug}',
      active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations(),
      round_started=round_started)

  round = get_round(event_slug, round_slug)
  matches = get_matches(event_slug, round_slug)

  dtnow = datetime.now()
  round_over = dtnow > round.end_time

  did_you_start, did_you_finish = did_you_vote(current_user.id, event_slug, round_slug)

  # if round_over:
  # - if we need tiebreaks, and you didn't start, then you can be the tiebreaker
  # - any other case (no tiebreaks needed, or tiebreaks needed but you already started), get blocked
  # did_you_start here gatekeeps tiebreakers to people who haven't started to vote yet
  # if we dislike this, change it I guess
  tiebreaks = needs_tiebreaker(count_votes(event_slug, round_slug))
  if round_over and (len(tiebreaks) == 0 or did_you_start):
    flash('Voting for this round is closed. See the results:')
    return redirect(url_for('results', event_slug=event_slug, round_slug=round_slug))

  class VoteForm(FlaskForm):
    pass

  for match_idx, match in enumerate(matches):
    match_num = match_idx + 1
    radio_choices = []

    candidates = db.session.scalars(match.candidates.select().order_by(Candidate.song_id)).all()
    current_vote = get_vote_in_match(current_user.id, match.id)
    if current_vote:
      current_vote_name = f'match{match.id}-{current_vote.song_id}'
    else:
      current_vote_name = None

    for candidate_idx, candidate in enumerate(candidates):

      song = db.session.scalar(sa.select(Song).where(Song.id == candidate.song_id))

      radio_choices.append((f'match{match.id}-{song.id}', Markup(f'<a href="{song.link}">{song.artist} – {song.title}</a>')))

    # Force tiebreak vote to vote in every tiebreaker.
    if round_over and match_num in tiebreaks:
      validators = [DataRequired()]
    else:
      validators = [Optional()]

    radio_field = RadioField(f'Match {match_num}:', choices=radio_choices, default=current_vote_name, validators=validators)

    # If round is not over, always show every match.
    # If round is over, only show matches that need tiebreaks.
    if not round_over or match_num in tiebreaks:
      setattr(VoteForm, f'match{match.id}', radio_field)

  setattr(VoteForm, 'submit', SubmitField('Submit'))

  form = VoteForm()

  if form.validate_on_submit():
    # same janky tiebreak logic as above
    if round_over and (len(tiebreaks) == 0 or did_you_start):
      flash('Voting for this round is closed. See the results:')
      return redirect(url_for('results', event_slug=event_slug, round_slug=round_slug))
    else:
      # if round is over, you are a tiebreaker, I think?
      add_vote(request.form, round_over)

      did_you_start, did_you_finish = did_you_vote(current_user.id, event_slug, round_slug)

      if round_over:
        flash('Tiebreaking vote(s) received. Check out the results:')
        return redirect(url_for('results', event_slug=event_slug, round_slug=round_slug))
      elif did_you_finish:
        flash('Vote received. While you wait, why not check out the results so far?')
        return redirect(url_for('results', event_slug=event_slug, round_slug=round_slug))
      elif did_you_start:
        flash('Your votes so far are saved, but you haven\'t voted in every match yet.')
        return redirect(url_for('vote', event_slug=event_slug, round_slug=round_slug))
      else:
        return redirect(url_for('vote', event_slug=event_slug, round_slug=round_slug))
  else:
    return render_template('vote.html', title=f'Vote in Round {round_slug}', 
      active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations(),
      form=form, did_you_start=did_you_start, did_you_finish=did_you_finish, round_over=round_over)

@app.route('/vote/<event_slug>/<round_slug>/delete-votes/', methods=['POST'])
def delete_votes(event_slug, round_slug):
  round = get_round(event_slug, round_slug)

  votes = get_votes_in_round(current_user.id, round.id)
  for vote in votes:
    db.session.delete(vote)
  db.session.commit()
  
  flash(f'Votes for {round.event.name} Round {round.round_slug} deleted.')
  return redirect(url_for('vote', event_slug=event_slug, round_slug=round_slug))

@app.route('/results/<event_slug>/<round_slug>/')
def results(event_slug, round_slug):

  # Attempt to populate before showing "unreleased" - so that when a round opens, somebody
  # can actually populate it.
  # In theory, this only does something the first time the user requests a round.
  populate_round(event_slug, round_slug)

  round_started = datetime.now() > get_round(event_slug, round_slug).start_time
  if not round_started or not is_round_populated(event_slug, round_slug):
    return render_template('unreleased.html', title=f'Results for Round {round_slug}',
      active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations(),
      round_started=round_started)

  round_over = datetime.now() > get_round(event_slug, round_slug).end_time
  if round_over:
    title = f'Final Results for Round {round_slug}'
  else:
    title = f'Results So Far for Round {round_slug}'

  match_lsts = count_votes(event_slug, round_slug)
  return render_template('results.html', title=title, 
    active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations(),
    match_lsts=match_lsts)


###################
# NOMINATE ROUTES #
###################

# Use this when a user submits a nomination (new or changed).
def edit_nomination(user_id, event_id, artist, title, link, pick_num):
  existing_pick = db.session.scalar(sa.select(Song)
    .filter(Song.user_id == user_id)
    .filter(Song.event_id == event_id)
    .filter(Song.pick_num == pick_num))

  # If pick is edited to be blank, clear out database.
  if artist == '' and title == '' and link == '':
    # If existing pick, clear it.
    if existing_pick is not None:
      db.session.delete(existing_pick)
      db.session.commit()
    # If no existing pick, just do nothing.
    return

  # If nothing was changed, do nothing.
  if existing_pick is not None:
    if artist == existing_pick.artist and title == existing_pick.title and link == existing_pick.link:
      return

  if existing_pick:
    existing_pick.artist = artist
    existing_pick.title = title
    existing_pick.link = link
    existing_pick.approved = 'PENDING' # new/modified noms are pending by default
    existing_pick.approval_message = ''
    existing_pick.pick_time = datetime.now()
    existing_pick = db.session.merge(existing_pick)
    db.session.commit()
  else:
    new_nom = Song(
      user_id=user_id,
      event_id=event_id,
      artist=artist,
      title=title,
      link=link,
      pick_num=pick_num,
      approved='PENDING',
      approval_message='',
      pick_time=datetime.now())
    db.session.add(new_nom)
    db.session.commit()

# Used to pre-populate the form with existing picks.
def get_pick(user_id, event_id, pick_num):
  existing_pick = db.session.scalar(sa.select(Song)
    .filter(Song.user_id == user_id)
    .filter(Song.event_id == event_id)
    .filter(Song.pick_num == pick_num))
  if existing_pick:
    return existing_pick
  else:
    return None


@app.route('/nominate/<event_slug>/', methods=['GET', 'POST'])
@login_required
def nominate(event_slug):
  
  if not current_user.is_verified:
    flash(f'To activate your account, prove it\'s you by posting the code "{current_user.verify_code}" on the NHC.')
    return redirect(url_for('index'))

  # This 404s if you try to submit noms for a nonexistent event. Cool.
  event = get_event(event_slug)

  # Get all pick statuses for all users.
  all_pick_statuses = get_all_pick_statuses(event_slug)

  class NominationForm(FlaskForm):
    # Checks only pick_num: If one is full, they must all be full.
    def check_pick(self, pick_num, artist, title, link):
      fields_filled = [artist != '', title != '', link != '']
      if any(fields_filled) and not all(fields_filled):
        raise ValidationError(f'Pick {pick_num} is missing at least one of artist/title/link.')

    # Checks that all picks up to (not including) pick_num are full.
    def check_submit(self, pick_num):
      pick1 = [self.pick1_artist.raw_data[0] != '', self.pick1_title.raw_data[0] != '', self.pick1_link.raw_data[0] != '']
      pick2 = [self.pick2_artist.raw_data[0] != '', self.pick2_title.raw_data[0] != '', self.pick2_link.raw_data[0] != '']
      pick3 = [self.pick3_artist.raw_data[0] != '', self.pick3_title.raw_data[0] != '', self.pick3_link.raw_data[0] != '']
      pick4 = [self.pick4_artist.raw_data[0] != '', self.pick4_title.raw_data[0] != '', self.pick4_link.raw_data[0] != '']
      
      if pick_num == 2:
        if any(pick2) and not all(pick1):
          raise ValidationError('Fill in pick 1 before filling in later ones.')
      if pick_num == 3:
        if any(pick3) and not (all(pick1) and all(pick2)):
          raise ValidationError('Fill in picks 1 and 2 before filling in later ones.')
      if pick_num == 4:
        if any(pick4) and not (all(pick1) and all(pick2) and all(pick3)):
          raise ValidationError('Fill in picks 1, 2, and 3 before filling in later ones.')

    def validate_pick1_artist(self, pick1_artist):
      self.check_pick(1, self.pick1_artist.raw_data[0], self.pick1_title.raw_data[0], self.pick1_link.raw_data[0])

    def validate_pick1_title(self, pick1_title):
      self.check_pick(1, self.pick1_artist.raw_data[0], self.pick1_title.raw_data[0], self.pick1_link.raw_data[0])

    def validate_pick1_link(self, pick1_link):
      self.check_pick(1, self.pick1_artist.raw_data[0], self.pick1_title.raw_data[0], self.pick1_link.raw_data[0])

    def validate_pick2_artist(self, pick2_artist):
      self.check_pick(2, self.pick2_artist.raw_data[0], self.pick2_title.raw_data[0], self.pick2_link.raw_data[0])
      self.check_submit(2)

    def validate_pick2_title(self, pick2_title):
      self.check_pick(2, self.pick2_artist.raw_data[0], self.pick2_title.raw_data[0], self.pick2_link.raw_data[0])
      self.check_submit(2)

    def validate_pick2_link(self, pick2_link):
      self.check_pick(2, self.pick2_artist.raw_data[0], self.pick2_title.raw_data[0], self.pick2_link.raw_data[0])
      self.check_submit(2)

    def validate_pick3_artist(self, pick3_artist):
      self.check_pick(3, self.pick3_artist.raw_data[0], self.pick3_title.raw_data[0], self.pick3_link.raw_data[0])
      self.check_submit(3)

    def validate_pick3_title(self, pick3_title):
      self.check_pick(3, self.pick3_artist.raw_data[0], self.pick3_title.raw_data[0], self.pick3_link.raw_data[0])
      self.check_submit(3)

    def validate_pick3_link(self, pick3_link):
      self.check_pick(3, self.pick3_artist.raw_data[0], self.pick3_title.raw_data[0], self.pick3_link.raw_data[0])
      self.check_submit(3)

    def validate_pick4_artist(self, pick4_artist):
      self.check_pick(4, self.pick4_artist.raw_data[0], self.pick4_title.raw_data[0], self.pick4_link.raw_data[0])
      self.check_submit(4)

    def validate_pick4_title(self, pick4_title):
      self.check_pick(4, self.pick4_artist.raw_data[0], self.pick4_title.raw_data[0], self.pick4_link.raw_data[0])
      self.check_submit(4)

    def validate_pick4_link(self, pick4_link):
      self.check_pick(4, self.pick4_artist.raw_data[0], self.pick4_title.raw_data[0], self.pick4_link.raw_data[0])
      self.check_submit(4)

  pick_status = {}
  pick_messages = {}

  # maybe the number of picks can be variable in the future
  # for now, hard-code 4 picks
  for pick_num in range(1, 5):
    existing_pick = get_pick(current_user.id, event.id, pick_num)

    if existing_pick:
      pick_status[pick_num] = existing_pick.approved
      pick_messages[pick_num] = existing_pick.approval_message
    else:
      pick_status[pick_num] = 'BLANK'
      pick_messages[pick_num] = ''

    # build form
    song_artist = StringField(f'Pick {pick_num} Artist', validators=[], default=None if existing_pick == None else existing_pick.artist)
    song_title = StringField(f'Pick {pick_num} Title', validators=[], default=None if existing_pick == None else existing_pick.title)
    song_link = StringField(f'Pick {pick_num} Link', validators=[], default=None if existing_pick == None else existing_pick.link)
    setattr(NominationForm, f'pick{pick_num}_artist', song_artist)
    setattr(NominationForm, f'pick{pick_num}_title', song_title)
    setattr(NominationForm, f'pick{pick_num}_link', song_link)

  setattr(NominationForm, 'submit', SubmitField('Submit'))
  form = NominationForm()

  if form.validate_on_submit():
    if datetime.now() > event.pick_deadline:
      flash(f'Nominations for {event.name} are closed and cannot be changed.')
      return redirect(url_for('nominate', event_slug=event_slug))
    for pick_num in range(1, 5):
      edit_nomination(
        user_id=current_user.id,
        event_id=event.id,
        artist=form[f'pick{pick_num}_artist'].raw_data[0],
        title=form[f'pick{pick_num}_title'].raw_data[0],
        link=form[f'pick{pick_num}_link'].raw_data[0],
        pick_num=pick_num
      )
    flash('Submission received.')
    return redirect(url_for('nominate', event_slug=event_slug))
  else:
    return render_template('nominate.html', title=f'Nominations for {event.name}', 
      active_rounds=get_active_rounds(), recent_rounds=get_recent_rounds(), active_nominations=get_active_nominations(),
      form=form, pick_status=pick_status, pick_messages=pick_messages, all_pick_statuses=all_pick_statuses)
