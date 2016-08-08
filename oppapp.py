# IMPORTS #
from datetime import datetime
from datetime import date
import date as ndate
from flask import Flask,session, request, flash, url_for, redirect, render_template, abort ,g, make_response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import asc
from flask.ext.login import LoginManager
from flask.ext.login import login_user , logout_user , current_user , login_required
from flask.ext import excel
from werkzeug.security import generate_password_hash, check_password_hash
import ast, re, uuid

# INITIALIZATION #
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ms.db'
app.config['SECRET_KEY'] = 'thesecret'
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# FUNCTION DEFINITIONS #
def allcansignup(): 
    # returns true if property "cansignup" is true for all users 
    # (used for sign-ups open/closed switch on editor page)
    return all([a[0] for a in Users.query.with_entities(Users.cansignup).all()])

def changesetting(usr, name, val):
    # settings are stored as JSON/python dict encoded as a string in users database table
    # this method allows easy setting of these settings
    sets = ast.literal_eval(usr.settings)
    sets[name] = val
    usr.settings = str(sets)
    db.session.commit()

# FLASK-SQLALCHEMY MANY-TO-MANY RELATIONSHIP TABLE (USERS <-> OPPS) #
relationship_table = db.Table('relationship_table',
    db.Column('user_id', db.Integer,db.ForeignKey('users.id'), nullable=False),
    db.Column('opps_id',db.Integer,db.ForeignKey('opps.id'),nullable=False),
    db.PrimaryKeyConstraint('user_id', 'opps_id') )
 
# USERS CLASS #
class Users(db.Model):
    id = db.Column(db.Integer , primary_key=True) # user's internal id for app
    fname = db.Column('fname', db.String(20)) # first name
    lname = db.Column('lname', db.String(20)) # last name
    password = db.Column('password' , db.String(250)) # definitely not the password
    editor = db.Column('editor', db.Boolean) # whether or not user can edit events
    cansignup = db.Column('cansignup', db.Boolean) # whether or not user can sign up for events
    email = db.Column('email',db.String(50),unique=True , index=True) # user's grove city college email address
    gccid = db.Column('gccid', db.Integer, unique=True) # user's grove city college student id
    settings = db.Column('settings', db.String) # settings, stored as JSON/python dict encoded as string
    registered_on = db.Column('registered_on' , db.DateTime) # date user registered (not really used)
    
    opps = db.relationship('Opps' , secondary = relationship_table, backref='users') # connects user to his or her opps

    # user methods
    def __init__(self ,password , email, admin):
        # does some initializing when user first registers
        self.set_password(password)
        self.email = email
        self.registered_on = datetime.utcnow()
        self.editor = admin
        self.cansignup = True
        self.fname = ''
        self.lname = ''
        self.settings = "{'bcc':0,'pastevents':{}}"
        

    def set_password(self , password):
        self.password = generate_password_hash(password)

    def check_password(self , password):
        return check_password_hash(self.password , password)

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.id)

    def __repr__(self):
        return '<User %r>' % (self.fname)
    
    def is_editor(self):
        # returns true if user can edit events
        return self.editor
        
    def get_setting(self, setting):
        # returns a specified user setting
        return ast.literal_eval(self.settings)[setting]
        
    def chg_setting(self, name, val):
	    sets = ast.literal_eval(self.settings)
	    sets[name] = val
	    self.settings = str(sets)
	    db.session.commit()
       
        
# OPPS CLASS #
class Opps(db.Model):
    id = db.Column(db.Integer, primary_key=True) # opp internal id for app
    name = db.Column(db.String) # opp event name
    date = db.Column(db.DateTime) # when opp starts (date and time)
    enddate = db.Column(db.DateTime) # when opp ends (date and time)
    techsneeded = db.Column(db.Integer) # the opposite of the number of techs that aren't needed
    desc = db.Column(db.String) # event location
    info = db.Column(db.String) # event extra information 
    uuid = db.Column(db.String)
    deleted = db.Column(db.Boolean)
    recurring = db.Column('recurring', db.Boolean) # recurring events, like chapels
    
    def __init__(self, name, desc):
        # more boring initialization stuff
        self.name = name
        self.date = datetime.utcnow()
        self.enddate = datetime.utcnow()
        self.desc = desc
        self.info = ""
        self.techsneeded = 0
        self.uuid = uuid.uuid4().hex
        self.deleted = False
        self.recurring = 0
        
    def get_timeline(self):
        # returns a number based on how now is related to when the event is
        now = datetime.now()
        if now < self.date:
            return 0 # if event is upcoming
        elif now > self.date and now < self.enddate:
            return 1 # if event is in progress
        elif now > self.enddate:
            return 2 # if event is over
    
    def get_timesecs(self):
        delta = self.date - datetime.now()
        return delta.seconds + delta.days*24*3600
    
    def get_natural(self, dort):
        if dort == 'd':
            return ndate.duration(self.date)
        elif dort == 't':
            return ndate.delta(self.enddate, self.date)[0]
    
    def is_today(self):
        if self.date.date() == date.today():
            return 1
    
    def get_shorttime(self, beginningorend):
        if beginningorend == 0:
            d = self.date
        else:
            d = self.enddate
        if d.strftime('%M') == '00':
            timepre = d.strftime('%-I')
        else:
            timepre = d.strftime('%-I:%M')
        if d.strftime('%p') == 'AM':
            timesuf = 'A'
        else:
            timesuf = 'P'
        return timepre + timesuf
    
# MAIN EVENTS PAGE #
@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    allusers = Users.query.all()
    
    if request.method == 'POST': # happens when form is submitted (a button is clicked on the page)
        
        if g.user.is_editor(): # happens if current user is an editor
            
            def getuserevent(addorremove): 
                # parses string sent by form (add user to/remove user from event)
                # returns the user and opp described by that string
                [userid,eventid] = request.form[addorremove].split(',')
                usr = Users.query.get(int(userid))
                opp = Opps.query.get(int(eventid))
                return [usr, opp]
                
            if 'addtoevent' in request.form: # if "add tech to event" button was clicked
                [usr, opp] = getuserevent('addtoevent')
                usr.opps.append(opp)
                
            if 'removefromevent' in request.form: # if tech is removed from an event
                [usr, opp] = getuserevent('removefromevent')
                usr.opps.remove(opp)
                flash(usr.fname + ' ' + usr.lname + ' removed from "' + opp.name + '"', 'success')
            
            if 'movetoevent' in request.form: # if tech is moved to different event
                [usrid, frmid, toid] =request.form['movetoevent'].split(',')
                usr = Users.query.get(int(usrid))
                frm = Opps.query.get(int(frmid))
                to = Opps.query.get(int(toid))
                usr.opps.remove(frm)
                usr.opps.append(to)
                flash(usr.fname + ' ' + usr.lname + ' moved from "' + frm.name + '" to "' + to.name + '"', 'success')
                
            if 'togglesignup' in request.form: # if "sign-ups open/closed" button is clicked
                if allcansignup():
                    for user in allusers:
                        user.cansignup = False
                    #flash('Sign-Ups are now closed.')
                else:
                    for user in allusers:
                        user.cansignup = True
                    #flash('Sign-Ups are now open.')             
                
        else: # if current user is not an editor
            if 'add' in request.form: # adding from "available events" to "my events"
                opp = Opps.query.get(int(request.form['add']))
                usr = Users.query.get(g.user.id)
                usr.opps.append(opp)
                
            if 'drop' in request.form: # dropping event from "my events"
                opp = Opps.query.get(int(request.form['drop']))
                usr = Users.query.get(g.user.id)
                usr.opps.remove(opp)
            
        db.session.commit()
            
    # if a button is not clicked, i.e. the page is just loaded normally
    if g.user.is_editor():
        # load editor page with all events
        todos = Opps.query.order_by(asc(Opps.date)).filter(Opps.recurring == 0).all() 
        return render_template('index_editor.html',todos=todos, allusers=allusers, allcansignup=allcansignup() )
    else:
        # load normal page, send user's chosen events and available events separately
        usr = Users.query.get(g.user.id)
        leftevents = db.session.query(Opps).filter(~Opps.users.any(Users.id == g.user.id)).order_by(asc(Opps.date)).all()
        myevents = db.session.query(Opps).filter(Opps.users.any(Users.id == g.user.id)).order_by(asc(Opps.date)).all()
        return render_template('index.html',leftevents = leftevents, myevents = myevents, today = datetime.now())

# RECURRING EVENT PAGE #
@app.route('/recurring', methods=['GET', 'POST'])
@login_required
def recurring():
    if not g.user.is_editor():
        flash('You must be an editor to access this page.','danger')
        return redirect(url_for('index'))
    events = Opps.query.order_by(asc(Opps.date)).filter(Opps.recurring == 1).all() 
    return render_template('recurring.html', events = events)
        

# NEW EVENT PAGE #
@app.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST': # form was submitted
        # do a whole bunch of form verification (is there a better way to do this?)
        if not request.form['title']:
            flash('Title is required', 'danger')
        elif not request.form['location']:
            flash('Location is required', 'danger')
        #elif not request.form['date']:
        #    flash('Date is required', 'danger')
        elif not request.form['time']:
            flash('Start time is requried', 'danger')
        #elif datetime.strptime(request.form['date']+request.form['time'],'%m/%d/%Y%I:%M %p') < datetime.now():
        #    flash('Event must occur in the future.', 'danger')
        elif not request.form['endtime']:
            flash('End time is required', 'danger')
        elif not request.form['ntechs']:
            flash('Number of techs is required', 'danger')

        else: # finally, if we pass inspection, add the event to the database
            title = request.form['title']
            todo = Opps(title, request.form['location'])
            if request.form['recurring'] == 'collapse-recur':
                todo.recurring = 1
                todo.date = datetime.strptime(request.form['options'],'%w')
                todo.enddate = datetime.strptime(request.form['options'],'%w')
                flash(request.form['options'])
            elif request.form['recurring'] == 'collapse-once':
                todo.recurring = 0
                todo.date = datetime.strptime(request.form['date']+request.form['time'],'%m/%d/%Y%I:%M %p')
                todo.enddate = datetime.strptime(request.form['date']+request.form['endtime'],'%m/%d/%Y%I:%M %p')
            todo.user = g.user
            todo.techsneeded = int(request.form['ntechs'])
            todo.info = request.form['info']
            db.session.add(todo)
            db.session.commit()
            flash('"' + title + '" was successfully created', 'success')
            flash(todo.uuid,'info')
            return redirect(url_for('index'))
        
    return render_template('new.html') # page was loaded

    
# EDIT EVENT PAGE #
@app.route('/todos/<int:todo_id>', methods = ['GET' , 'POST'])
@login_required
def show_or_update(todo_id):
    if not g.user.is_editor():
        flash('You are not allowed to edit.', 'danger')
        return redirect(url_for('index'))
    todo_item = Opps.query.get(todo_id)
    if request.method == 'GET':
        return render_template('view.html',todo=todo_item)
    #if todo_item.users.id == g.user.id:
    if request.form['submit'] == 'submit':
        todo_item.name = request.form['title']
        todo_item.desc = request.form['location']
        todo_item.date = datetime.strptime(request.form['date']+request.form['time'],'%m/%d/%Y%I:%M %p')
        todo_item.enddate = datetime.strptime(request.form['date']+request.form['endtime'],'%m/%d/%Y%I:%M %p')
        todo_item.techsneeded = request.form['ntechs']
        todo_item.info = request.form['info']
        flash('Event updated.', 'info')
    else:
        db.session.delete(todo_item)
        flash('Event deleted.', 'info')
    #print request.form['date']
    #todo_item.done  = ('done.%d' % todo_id) in request.form
    db.session.commit()
    return redirect(url_for('index'))
    flash('You are not authorized to edit this todo item','danger')
    return redirect(url_for('show_or_update',todo_id=todo_id))
    
# CLEAR PAST EVENTS METHOD #
@app.route('/clear')
def clear():
    opps = Opps.query.all()
    for opp in opps:
        if opp.get_timeline() == 2:
            opp.deleted = True
    db.session.commit()
    flash('Cleared Past Events.','info')
    return redirect(url_for('index'))
    
# DOWNLOAD CSV RECEIPT METHOD #
@app.route('/download')
@login_required
def download():
    result = [['Event','Date','Techs']]
    for opp in Opps.query.all():
        item = [opp.name, opp.date]
        for usr in opp.users:
            item.append(usr.fname +' '+ usr.lname)
        result.append(item)

    result = excel.make_response_from_array(result, 'csv', status=200, file_name='opps')
    response = make_response(result)
    response.headers["Content-Disposition"] = "attachment; filename=opps.csv"
    return response 
   
@app.route('/mailreceipt')
@login_required
def mailreceipt():
    mailstring = ""
    for opp in Opps.query.all():
        if opp.get_timeline() != 2:
            mailstring += opp.name + " - " + str(opp.date.strftime('%a, %b %-d, %Y')) + "\n"
            for tech in opp.users:
                mailstring += tech.fname + " " + tech.lname + ", "
            mailstring += "\n\n"
    return redirect('mailto:' + g.user.email + '?subject=Work Opps&body=' + mailstring)

# USER PROFILE PAGE #
@app.route('/profile/<int:uid>', methods=['GET','POST'])
def profile(uid):
    if request.method == 'POST':
        if 'changepassword' in request.form:
            if g.user.check_password(request.form['oldpwd']):
                if request.form['newpwd1'] == request.form['newpwd2']:
                    g.user.set_password(request.form['newpwd1'])
                    db.session.commit()
                    flash('Password successfully changed.','success')
                else:
                    flash('New passwords do not match.','danger')
            else:
                flash('Old password incorrect','danger')
                
        if 'bcc' in request.form:
            if request.form['bcc'] == "on":
                changesetting(g.user, 'bcc', 1)
            else:
                changesetting(g.user, 'bcc', 0)

    users = Users.query.filter(Users.id != uid).order_by(asc(Users.lname)).all()
    #for usr in Opps.query.all():
        #usr.recurring = 0
    #db.session.commit()
    usr = Users.query.get(uid)
    #history = Opps.query.filter(Opps.uuid.in_(usr.get_setting('pastevents'))).all()
    return render_template('profile.html', users = users, usr = usr)

# REGISTER NEW USER PAGE #
@app.route('/register' , methods=['GET','POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    #if 'admin' in request.form:
    #    isadmin = 1
    #else:
    #    isadmin = 0
    if not request.form['fname'] or not request.form['lname']:
        flash ('Please enter your name.','danger')
    elif not request.form['email']:
        flash('Please enter an email address.','danger')
    elif not re.match(r"(.*@gcc\.edu)", request.form['email']):
        flash('Please enter a valid GCC email address.','danger')
    elif not re.match(r"(\d{6})", request.form['gccid']):
        flash('Please enter a valid GCC ID number','danger')
    elif request.form['password'] != request.form['password2']:
        flash('Passwords do not match!','danger')
    
    else:
        user = Users(request.form['password'],request.form['email'], 0)
        user.fname = request.form['fname'].title()
        user.lname = request.form['lname'].title()
        user.gccid = int(request.form['gccid'])
        db.session.add(user)
        db.session.commit()
        flash('User successfully registered','success')
        return redirect(url_for('login'))
    return render_template('register.html')

# LOGIN PAGE #
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    email = request.form['email']
    password = request.form['password']
    remember_me = False
    if 'remember_me' in request.form:
        remember_me = True
    registered_user = Users.query.filter_by(email=email).first()
    if registered_user is None:
        flash('Username is invalid' , 'danger')
        return redirect(url_for('login'))
    if not registered_user.check_password(password):
        flash('Password is invalid','danger')
        return redirect(url_for('login'))
    login_user(registered_user, remember = remember_me)
    #flash('Logged in successfully')
    return redirect(request.args.get('next') or url_for('index'))

# LOGOUT METHOD #
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index')) 

@login_manager.user_loader
def load_user(id):
    return Users.query.get(int(id))

@app.before_request
def before_request():
    g.user = current_user

# RUN APP #
if __name__ == '__main__':
    app.run(debug=True)
