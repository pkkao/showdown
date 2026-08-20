from dataclasses import dataclass
from datetime import datetime

from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

@dataclass
class User(UserMixin, db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  username: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  # thinking of temp hacking this as like ryan@nohomers.net
  email: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

  songs: so.WriteOnlyMapped['Song'] = so.relationship(back_populates='user')

  def set_password(self, password):
    self.password_hash = generate_password_hash(password)

  def check_password(self, password):
    return check_password_hash(self.password_hash, password)

  def __str__(self):
    return self.username

@login.user_loader
def load_user(id):
  return db.session.get(User, int(id))

@dataclass
class Event(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  event_slug: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True) # wi27-music
  name: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True) # Winter 2027 Music Showdown
  pick_deadline: so.Mapped[datetime] = so.mapped_column(sa.DateTime())

  rounds: so.WriteOnlyMapped['Round'] = so.relationship(back_populates='event')
  songs: so.WriteOnlyMapped['Song'] = so.relationship(back_populates='event')

  def __str__(self):
    return self.event_slug

@dataclass
class Round(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  event_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Event.id), index=True)
  round_slug: so.Mapped[str] = so.mapped_column(sa.String(256), index=True) # 2a
  start_time: so.Mapped[datetime] = so.mapped_column(sa.DateTime())
  end_time: so.Mapped[datetime] = so.mapped_column(sa.DateTime())

  # the round (singular) that the winners of this round all advance to
  next_round_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey('round.id'), index=True)

  event: so.Mapped['Event'] = so.relationship(back_populates='rounds')
  matches: so.WriteOnlyMapped['Match'] = so.relationship(back_populates='round')

  # one or more prev_rounds (plural) have their winners enter this round
  # the winners of this round all advance to next_round (singular)
  prev_rounds: so.Mapped[list['Round']] = so.relationship('Round', back_populates='next_round', remote_side=[next_round_id])
  next_round: so.Mapped['Round | None'] = so.relationship('Round', back_populates='prev_rounds', remote_side=[id])

  def __str__(self):
    return f'{self.event_slug}-{self.round_slug}'

@dataclass
class Song(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
  event_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Event.id), index=True)
  artist: so.Mapped[str] = so.mapped_column(sa.String(256), index=True)
  title: so.Mapped[str] = so.mapped_column(sa.String(256), index=True)
  link: so.Mapped[str] = so.mapped_column(sa.String(256), index=True)
  pick_num: so.Mapped[int] = so.mapped_column(index=True)
  pick_time: so.Mapped[datetime] = so.mapped_column(sa.DateTime())
  approved: so.Mapped[str] = so.mapped_column(sa.String(256), index=True)
  approval_message: so.Mapped[str] = so.mapped_column(sa.String(1024), nullable=True)

  user: so.Mapped['User'] = so.relationship(back_populates='songs')
  event: so.Mapped['Event'] = so.relationship(back_populates='songs')

  def __str__(self):
    return f'{self.artist} – {self.title}'

@dataclass
class Match(db.Model):

  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  round_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Round.id), index=True)

  round: so.Mapped['Round'] = so.relationship(back_populates='matches')
  votes: so.WriteOnlyMapped['Vote'] = so.relationship(back_populates='match')
  candidates: so.WriteOnlyMapped['Candidate'] = so.relationship(back_populates='match')

  def __str__(self):
    return f'{self.round} match {self.id}'

@dataclass
class Vote(db.Model):
  match_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Match.id), index=True, primary_key=True)
  user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True, primary_key=True)
  song_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Song.id), index=True)
  is_tiebreaker: so.Mapped[bool] = so.mapped_column(default=False)

  sa.UniqueConstraint(match_id, user_id, name='vote once per match')

  match: so.Mapped['Match'] = so.relationship(back_populates='votes')

  def __str__(self):
    return f'{self.match}, {self.user_id} voted for {self.song_id}'

@dataclass
class Candidate(db.Model):
  song_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Song.id), index=True, primary_key=True)
  match_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Match.id), index=True, primary_key=True)

  match: so.Mapped['Match'] = so.relationship(back_populates='candidates')
