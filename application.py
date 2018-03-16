from flask import Flask, render_template, request, redirect, jsonify, url_for, flash, g
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Team, Player, User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests
from functools import wraps

app = Flask(__name__)

CLIENT_ID = json.loads(open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "NBA Teams Application"

# Connect to the Database and creates a session
engine = create_engine('sqlite:///basketballteam.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access token received %s " % access_token

    app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(
        open('fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"
    '''
        Due to the formatting for the result from the server token exchange we
        have to split the token first on commas and select the first index
        which gives us the key : value for the server access token then we split
        it on colons to pull out the actual token value and replace the
        remaining quotes with nothing so that it can be used directly in the
        graph api calls
    '''
    token = result.split(',')[0].split(':')[1].replace('"', '')

    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # print "url sent for API access:%s"% url
    # print "API JSON result: %s" % result
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]

    # The token must be stored in the login_session in order to properly logout
    login_session['access_token'] = token

    # Get user picture
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

    flash("Now logged in as %s" % login_session['username'])
    return output


@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id, access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return "you have been logged out"


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps(
            'Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps(
            'Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# Disconnect based on provider
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            del login_session['access_token']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showTeams'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showTeams'))


# Require Login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if user is None:
            return redirect(url_for('showLogin', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


# JSON APs for Team information
@app.route('/team/<int:team_id>/players/JSON')
def teamPlayersJSON(team_id):
    team = session.query(Team).filter_by(id=team_id).one()
    players = session.query(Player).filter_by(team_id=team_id).all()
    return jsonify(TeamPlayers=[i.serialize for i in players])


@app.route('/team/<int:team_id>/players/<int:player_id>/JSON')
def playersJSON(team_id, player_id):
    playerInfo = session.query(Player).filter_by(id=player_id).one()
    return jsonify(playerInfo=playerInfo.serialize)


@app.route('/team/JSON')
def teamsJSON():
    teams = session.query(Team).all()
    return jsonify(teams=[t.serialize for t in teams])


# Homepage. List all of the NBA teams
@app.route('/')
@app.route('/team/')
def showTeams():
    teams = session.query(Team).all()
    if 'username' not in login_session:
        return render_template('publicTeams.html', teams=teams)
    else:
        return render_template('teams.html', teams=teams)


# Create a new team
@login_required
@app.route('/team/new/', methods=['GET', 'POST'])
def newTeam():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newTeam = Team(name=request.form['name'], city=request.form['city'], state=request.form['state'], conference=request.form['conference'])
        session.add(newTeam)
        session.commit()
        return redirect(url_for('showTeams'))
    else:
        return render_template('newTeam.html')


# Edit a Team
@app.route('/team/<int:team_id>/edit/', methods=['GET', 'POST'])
def editTeam(team_id):
    if 'username' not in login_session:
        return redirect('/login')
    editTeam = session.query(Team).filter_by(id=team_id).one()
    if editTeam.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not allowed to edit this team.');}</script><body onload='myFunction()'>"
    if request.method == 'POST':
        if request.form['name']:
            editTeam.name = request.form['name']
        if request.form['city']:
            editTeam.city = request.form['city']
        if request.form['state']:
            editTeam.state = request.form['state']
        if request.form['conference']:
            editTeam.conference = request.form['conference']
        session.add(editTeam)
        session.commit()
        return redirect(url_for('showTeams'))
    else:
        return render_template('editTeam.html', team=editTeam)


# Delete a Team
@app.route('/team/<int:team_id>/delete/', methods=['GET', 'POST'])
def deleteTeam(team_id):
    if 'username' not in login_session:
        return redirect('/login')
    teamToDelete = session.query(Team).filter_by(id=team_id).one()
    if teamToDelete.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not allowed to delete this team.');}</script><body onload='myFunction()'>"
    if request.method == 'POST':
        session.delete(teamToDelete)
        session.commit()
        return redirect('showTeams', team_id=team_id)
    else:
        return render_template('deleteTeam.html', team=teamToDelete)


# List the players of the selected team
@app.route('/team/<int:team_id>/players/')
@app.route('/team/<int:team_id>/')
def showPlayers(team_id):
    team = session.query(Team).filter_by(id=team_id).one()
    creator = getUserInfo(team.user_id)
    players = session.query(Player).filter_by(team_id=team_id).all()
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('publicPlayers.html', players=players, team=team, creator=creator)
    else:
        return render_template('players.html', players=players, team=team, creator=creator)


# Add a new player
@app.route('/team/<int:team_id>/players/new/', methods=['GET', 'POST'])
def newPlayers(team_id):
    if 'username' not in login_session:
        return redirect('/login')
    team = session.query(Team).filter_by(id=team_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You can only add players to teams you have created.');}</script><body onload='myFunction()'>"
    if request.method == 'POST':
        newPlayer = Player(
            firstName=request.form['firstName'],
            lastName=request.form['lastName'],
            position=request.form['position'],
            playerNum=request.form['playerNum'],
            height=request.form['height'],
            weight=request.form['weight'],
            age=request.form['age'],
            birthplace=request.form['birthplace'],
            college=request.form['college'],
            role=request.form['role'],
            team_id=team_id)
        session.add(newPlayer)
        session.commit()
        return redirect(url_for('showPlayers', team_id=team_id, players_id=player_id))
    else:
        return render_template('newplayers.html', team_id=team_id)
    return render_template('newPlayers.html', team=team)


# Shows infromation about the selected player
@app.route('/team/<int:team_id>/players/<int:player_id>/playerinfo/')
@app.route('/team/<int:team_id>/players/<int:player_id>/')
def showPlayerInfo(team_id, player_id):
    players = session.query(Player).filter_by(id=player_id)
    team = session.query(Team).filter_by(id=team_id).one()
    return render_template('playerinfo.html', players=players, team=team)


# Edit a player
@app.route('/team/<int:team_id>/players/<int:player_id>/edit/', methods=['GET', 'POST'])
def editPlayer(team_id, player_id):
    if 'username' not in login_session:
        return redirect('/login')
    editPlayer = session.query(Player).filter_by(id=player_id).one()
    team = session.query(Team).filter_by(id=team_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You can only edit players on teams you have created.');}</script><body onload='myFunction()'>"
    if request.method == 'POST':
        if request.form['firstName']:
            editPlayer.name = request.form['firstName']
        if request.form['lastName']:
            editPlayer.name = request.form['lastName']
        if request.form['position']:
            editPlayer.position = request.form['position']
        if request.form['playerNum']:
            editPlayer.name = request.form['playerNum']
        if request.form['height']:
            editPlayer.name = request.form['height']
        if request.form['weight']:
            editPlayer.name = request.form['weight']
        if request.form['age']:
            editPlayer.name = request.form['age']
        if request.form['birthplace']:
            editPlayer.name = request.form['birthplace']
        if request.form['college']:
            editPlayer.name = request.form['College']
        if request.form['role']:
            editPlayer.name = request.form['role']
        session.add(editPlayer)
        session.commit()
        return redirect(url_for('showPlayers', team_id=team_id))
    else:
        return render_template(
            'editplayerinfo.html', team_id=team_id,
            player_id=player_id, player=editPlayer)


# Delete a player
@app.route('/team/<int:team_id>/players/<int:player_id>/delete/', methods=['GET', 'POST'])
def deletePlayer(team_id, player_id):
    if 'username' not in login_session:
        return redirect('/login')
    playerToDelete = session.query(Player).filter_by(id=player_id).one()
    team = session.query(Team).filter_by(id=team_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You can only delete players on teams you have created.');}</script><body onload='myFunction()'>"
    if request.method == 'POST':
        session.delete(playerToDelete)
        session.commit()
        return redirect(url_for('showPlayers', team_id=team_id))
    else:
        return render_template('deleteplayer.html', player=playerToDelete)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
