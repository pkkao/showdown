from flask import render_template, flash, redirect, request, url_for
from app import app

from flask_wtf import FlaskForm
from wtforms import RadioField, SubmitField
from wtforms.validators import Optional

from flask_login import current_user, login_user, login_required, logout_user

import sqlalchemy as sa
from app import db
from app.models import User, Event, Round, Song, Match, Vote, Candidate
from app.forms import LoginForm, RegistrationForm

import datetime
import pytz
from urllib.parse import urlsplit
import re

def get_active_rounds():
  dtnow = datetime.datetime.now()
  rounds = db.session.scalars(sa.select(Round).filter(Round.start_time < dtnow).filter(dtnow < Round.end_time)).all()

  active_rounds = []
  for round in rounds:

    matches_in_round = len(get_matches(round.event.event_slug, round.round_slug))

    did_you_vote = get_votes_in_round(round.id)

    did_you_start = len(did_you_vote) > 0
    did_you_finish = len(did_you_vote) == matches_in_round

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

# Get a list of the current user's votes for a specific round.
def get_votes_in_round(round_id):
  return db.session.scalars(sa.select(Vote, Match)
      .filter(Vote.match_id == Match.id) # table join
      .filter(Vote.user_id == current_user.id) # find your votes
      .filter(Match.round_id == round_id) # find votes in current round
    ).all()

# Get the current user's vote for a specific match.
def get_vote_in_match(match_id):
  return db.session.scalar(sa.select(Vote)
    .filter(Vote.match_id == match_id) # find the specific match
    .filter(Vote.user_id == current_user.id) # find your vote
  )

def get_round(event_slug, round_slug):
  round = db.one_or_404(sa.select(Round, Event).filter(Round.event_id == Event.id).filter(Round.round_slug == round_slug).filter(Event.event_slug == event_slug))
  return round

def get_matches(event_slug, round_slug):
  round = db.one_or_404(sa.select(Round, Event).filter(Round.event_id == Event.id).filter(Round.round_slug == round_slug).filter(Event.event_slug == event_slug))
  matches = db.session.scalars(round.matches.select().order_by(Match.id)).all()
  return matches

def get_songs(match):
  songs = []
  candidates = db.session.scalars(match.candidates.select().order_by(Candidate.song_id)).all()
  for candidate in candidates:
    song = db.session.scalar(sa.select(Song).where(Song.id == candidate.song_id))
    songs.append(song)
  return songs

def get_voter_username(vote):
  return db.session.scalar(sa.select(User).where(User.id == vote.user_id)).username

def count_votes(event_slug, round_slug):
  tallies = []
  voters = []

  matches = get_matches(event_slug, round_slug)

  for match in matches:
    tally = []
    voter = []
    for song_idx, song in enumerate(get_songs(match)):
      votes = db.session.scalars(sa.select(Vote).where(Vote.match_id == match.id).where(Vote.song_id == song.id)).all()
      tally.append(len(votes))
      voter.append([get_voter_username(v) for v in votes])
    tallies.append(tally)
    voters.append(voter)

  return tallies, voters

def add_vote(submission):
  user_id = current_user.id
  for match in submission:
    if 'match' in match:
      match_id = int(re.sub(r'match', '', match))
      song = submission[match]
      song_id = int(re.search(r".*-(.*)", song).group(1))
      vote = Vote(match_id=match_id, user_id=user_id, song_id=song_id)
      db.session.merge(vote)
  db.session.commit()

@app.route('/')
def index():
  round = get_round('su26-music', '1A') # temp

  if current_user.is_authenticated:
    un = f'You are: {current_user.username}'
  else:
    un = 'You are: Anonymous'
  return render_template('debug.html', debug=un, active_rounds=get_active_rounds())

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
  return render_template('login.html', title='Sign In', form=form, active_rounds=get_active_rounds())

@app.route('/logout')
def logout():
  logout_user()
  return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
  round = get_round('su26-music', '1A') # temp

  if current_user.is_authenticated:
    return redirect(url_for('index'))
  form = RegistrationForm()
  if form.validate_on_submit():
    user = User(username=form.username.data, email=form.email.data)
    user.set_password(form.password.data)
    db.session.add(user)
    db.session.commit()
    flash(f'Registered as {user.username}')
    return redirect(url_for('login'))
  return render_template('register.html', title='Register', form=form, active_rounds=get_active_rounds())

@app.route('/vote/<event_slug>/<round_slug>', methods=['GET', 'POST'])
@login_required
def vote(event_slug, round_slug):

  round = get_round(event_slug, round_slug)
  matches = get_matches(event_slug, round_slug)

  class VoteForm(FlaskForm):
    pass

  for match_idx, match in enumerate(matches):
    match_num = match_idx + 1
    radio_choices = []

    candidates = db.session.scalars(match.candidates.select().order_by(Candidate.song_id)).all()
    current_vote = get_vote_in_match(match.id)
    current_vote_name = f'match{match.id}-{current_vote.song_id}'

    for candidate_idx, candidate in enumerate(candidates):

      song = db.session.scalar(sa.select(Song).where(Song.id == candidate.song_id))

      radio_choices.append((f'match{match.id}-{song.id}', f'{song.artist} – {song.title}'))

    radio_field = RadioField(f'Match {match_num}:', choices=radio_choices, default=current_vote_name, validators=[Optional()])
    setattr(VoteForm, f'match{match.id}', radio_field)

  setattr(VoteForm, 'submit', SubmitField('Submit'))

  form = VoteForm()

  if form.validate_on_submit():
    flash('Vote received. While you wait, why not check out the results so far?')
    add_vote(request.form)
    return redirect(url_for('results', event_slug=event_slug, round_slug=round_slug))
  else:
    return render_template('vote.html', title='Vote', active_rounds=get_active_rounds(), matches=matches, form=form)


@app.route('/results/<event_slug>/<round_slug>')
def results(event_slug, round_slug):
  round = get_round(event_slug, round_slug)
  matches_db = get_matches(event_slug, round_slug)
  matches = []

  for match in matches_db:
    matches.append(get_songs(match))

  tallies, voters = count_votes(event_slug, round_slug)
  return render_template('results.html', title='Results', active_rounds=get_active_rounds(), matches=matches, tallies=tallies, voters=voters)