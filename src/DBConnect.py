from MySQLdb.cursors import SSCursor
from Properties import Properties
from Singleton import Singleton
from sys import stderr
import MySQLdb
import exceptions
import numpy
import string
import sys
import threading
import traceback
import re

verbose = True

p = Properties.getInstance()

class DBException(Exception):
    def __str__(self):
        filename, line_number, function_name, text = traceback.extract_tb(sys.last_traceback)[-1]
        return "ERROR <%s>: "%(function_name) + self.args[0] + '\n'


def image_key_columns(table_name=None):
    """Return, as a tuple, the names of the columns that make up the
    image key.  If table_name is not None, use it to qualify each
    column name."""
    if table_name is None:
        qualifier = ""
    else:
        qualifier = table_name + "."
    if p.table_id:
        return (qualifier+p.table_id, qualifier+p.image_id)
    else:
        return (qualifier+p.image_id,)

def object_key_columns():
    """Return, as a tuple, the names of the columns that make up the
    object key."""
    if p.table_id:
        return (p.table_id, p.image_id, p.object_id)
    else:
        return (p.image_id, p.object_id)


def GetWhereClauseForObjects(obKeys):
    '''
    Return a SQL WHERE clause that matches any of the given object keys.
    Example: GetWhereClauseForObjects([(1, 3), (2, 4)]) => 'WHERE 
    ImageNumber=1 AND ObjectNumber=3 OR ImageNumber=2 AND ObjectNumber=4'
    '''
    return " OR ".join([" AND ".join([col + '=' + str(value)
                                      for col, value in zip(object_key_columns(), obKey)])
                        for obKey in obKeys])


def GetWhereClauseForImages(imKeys):
    '''
    Return a SQL WHERE clause that matches any of the give image keys.
    Example: GetWhereClauseForImages([(3,), (4,)]) => 'WHERE
    ImageNumber=3 OR ImageNumber=4'
    '''
    return " OR ".join([" AND ".join([col + '=' + str(value)
                                      for col, value in zip(image_key_columns(), imKey)])
                        for imKey in imKeys])


def UniqueObjectClause():
    '''
    Returns a clause for specifying a unique object in MySQL.
    Example: "SELECT "+UniqueObjectClause()+" FROM <mydb>;" would return all object keys
    '''
    return ','.join(object_key_columns())


def UniqueImageClause(table_name=None):
    '''
    Returns a clause for specifying a unique image in MySQL.
    Example: "SELECT <UniqueObjectClause()> FROM <mydb>;" would return all image keys 
    '''
    return ','.join(image_key_columns(table_name))




#
# TODO: Rename _Execute, _Connect, _GetNextResult, etc
#       If users can use non-DB tables then all DB specific functions should be
#       completely abstracted.
class DBConnect(Singleton):
    '''
    DBConnect abstracts calls to MySQLdb.
    '''
    def __init__(self):
        self.classifierColNames = None
        self.connections = {}
        self.cursors = {}
        self.connectionInfo = {}

    def __str__(self):
        return string.join([ (key + " = " + str(val) + "\n")
                            for (key, val) in self.__dict__.items()])


    def Connect(self, db_host, db_user, db_passwd, db_name):
        connID = threading.currentThread().getName()
        # If this connection ID already exists print a warning
        if connID in self.connections.keys():
            if self.connectionInfo[connID] == (db_host, db_user, db_passwd, db_name):
                print 'WARNING <DBConnect.Connect>: Already connected to %s as %s@%s (connID = "%s").' % (db_name, db_user, db_host, connID)
            else:
                print 'WARNING <DBConnect.Connect>: connID "%s" is already in use. Close this connection first.' % (connID)
            return True

        # MySQL database: connect to db normally
        if p.db_type.lower() == 'mysql':
            try:
                conn = MySQLdb.connect(host=db_host, db=db_name, user=db_user, passwd=db_passwd)
                self.connections[connID] = conn
                self.cursors[connID] = SSCursor(conn)
                self.connectionInfo[connID] = (db_host, db_user, db_passwd, db_name)
                if verbose:
                    print 'Connected to database: %s as %s@%s (connID = "%s").' % (db_name, db_user, db_host, connID)
                return True
            except MySQLdb.Error, e:
                raise DBException, 'Failed to connect to database: %s as %s@%s (connID = "%s").\n' % (db_name, db_user, db_host, connID)
                return False
            
        # SQLite database: create database from file
        elif p.db_type.lower() == 'sqlite':
            
            from pysqlite2 import dbapi2 as sqlite

            self.connections[connID] = sqlite.connect('CPA_DB')
            self.cursors[connID] = self.connections[connID].cursor()
            self.connectionInfo[connID] = ('sqlite', 'cpa_user', '', 'CPA_DB')
            self.connections[connID].create_function('greatest', -1, max)
            
            # TODO:
            # Check if a SQLite DB has already been populated.
            # If so prompt user for whether to use it.
            try:
                nImages = len(self.GetAllImageKeys())
            except Exception:
                pass
            else:
                return True

#                # Try prompting the user with a wx dialog:
#                try:
#                    import wx
#                    dlg = wx.MessageDialog(None, 'Classifier found an existing SQLite database with %d images.\nUse this database?'%(nImages),
#                                        'Use existing SQLite DB?', 
#                                       wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
#                    answer = dlg.ShowModal()
##                    This acts wanky
#                    print answer, wx.YES, wx.NO
#                    if answer == wx.YES:
#                        return True
#                # If there is no wx App, then prompt in the console:
#                except Exception, e:
#                    print e
#                    print 'Classifier found an existing SQLite database with %d images.\nUse this database? (y/n)'%(nImages)
#                    answer = sys.stdin.readline()
#                    if answer.strip().lower() =='y':
#                        return True
            
            # If this is the first connection, then we need to create the DB from the files
            if len(self.connections) == 1:
                print 'No database info specified. Will attempt to load tables from file.'
                try:
                    fimg = open(p.image_csv_file)
                except IOError:
                    raise Exception, 'Failed to open image_csv_file from file. Check your properties file.' % (p.image_csv_file)
                    return False
                try:
                    fobj = open(p.object_csv_file)
                except:
                    raise Exception, 'Failed to open object_csv_file from file. Check your properties file.' % (p.object_csv_file)
                    return False
                else:
                    fimg.close()
                    fobj.close()
                    self.CreateSQLiteDB()
            return True
        
        # Unknown database type
        else:
            raise DBException, "Unknown db_type in properties: '%s'\n"%(p.db_type)


    def Disconnect(self):
        for connID in self.connections.keys():
            self.CloseConnection(connID)
        self.connections = {}
        self.cursors = {}
        self.connectionInfo = {}
        self.classifierColNames = None
        
    
    def CloseConnection(self, connID=None):
        if not connID:
            connID = threading.currentThread().getName()
        if connID in self.connections.keys():
            self.connections[connID].commit()
            self.cursors.pop(connID)
            self.connections.pop(connID).close()
            (db_host, db_user, db_passwd, db_name) = self.connectionInfo.pop(connID)
            print 'Closed connection: %s as %s@%s (connID="%s").' % (db_name, db_user, db_host, connID)
        else:
            print 'WARNING <DBConnect.CloseConnection>: No connection ID "%s" found.' %(connID)


    def Execute(self, query, silent=False):
        # Grab a new connection if this is a new thread
        connID = threading.currentThread().getName()
        if not connID in self.connections.keys():
            self.Connect(db_host=p.db_host, db_user=p.db_user, db_passwd=p.db_passwd, db_name=p.db_name)
        # Test for lost connection
        try:
            self.connections[connID].ping()
        except MySQLdb.OperationalError, message:
            print 'Lost connection to database. Attempting to reconnect.'
            self.CloseConnection(connID)
            self.Connect(db_host=p.db_host, db_user=p.db_user, db_passwd=p.db_passwd, db_name=p.db_name)
        except AttributeError:
            pass # SQLite doesn't know ping.
        
        # Finally make the query
        try:
            if verbose and not silent: print '[%s] %s'%(connID, query)
            self.cursors[connID].execute(query)
        except MySQLdb.Error, e:
            raise DBException, 'Database query failed for connection "%s"\n\t%s\n\t%s\n' %(connID, query, e)
        except KeyError, e:
            raise DBException, 'No such connection: "%s".\n' %(connID)
            
            
    def Commit(self):
        connID = threading.currentThread().getName()
        try:
            print '[%s] Commit'%(connID)
            self.connections[connID].commit()
        except MySQLdb.Error, e:
            raise DBException, 'Commit failed for connection "%s"\n\t%s\n' %(connID, e)
        except KeyError, e:
            raise DBException, 'No such connection: "%s".\n' %(connID)
            


    def GetNextResult(self):
        connID = threading.currentThread().getName()
        try:
            return self.cursors[connID].next()
        except MySQLdb.Error, e:
            raise DBException, 'Error retrieving next result from database.\n'
            return None
        except StopIteration, e:
            return None
        except KeyError, e:
            raise DBException, 'No such connection: "%s".\n' %(connID)
        
        
    def GetResultsAsList(self):
        connID = threading.currentThread().getName()
        ''' Returns a list of results retrieved from the last execute query. '''
        r = self.GetNextResult()
        l = []
        while r:
            l.append(r)
            r = self.GetNextResult()
        return l
    
    
    
    
    
    def GetObjectIDAtIndex(self, imKey, index):
        '''
        Returns the true object ID of the nth object in an image.
        Note: This must be used when object IDs in the DB aren't
              contiguous starting at 1.
              (eg: if some objects have been removed)
        '''
        imNum = imKey[-1]
        if p.table_id:
            tblNum = imKey[0]
            self.Execute('SELECT %s FROM %s WHERE %s=%s AND %s=%s LIMIT %s,1'
                       %(p.object_id, p.object_table, p.table_id, tblNum, p.image_id, imNum, index-1))
            obNum = self.GetResultsAsList()
            obNum = obNum[0][0]
        else:
            self.Execute('SELECT %s FROM %s WHERE %s=%s LIMIT %s,1'
                       %(p.object_id, p.object_table, p.image_id, imNum, index-1))
            obNum = self.GetResultsAsList()
            obNum = obNum[0][0]
        return tuple(list(imKey)+[int(obNum)])

    
    
    def GetPerImageObjectCounts(self):
        ''' 
        Returns a list of (imKey, obCount) tuples. 
        '''
        select = "SELECT "+UniqueImageClause()+", COUNT("+p.object_id+") FROM "+str(p.object_table)+" GROUP BY "+UniqueImageClause()
        self.Execute(select)
        return self.GetResultsAsList()
    
    
    def GetAllImageKeys(self):
        ''' 
        Returns a list of all image keys in the image_table. 
        '''
        select = "SELECT "+UniqueImageClause()+" FROM "+p.image_table+" GROUP BY "+UniqueImageClause()
        self.Execute(select)
        return self.GetResultsAsList()
    
    
    def GetObjectCoords(self, obKey):
        ''' 
        Returns the specified object's x, y coordinates in an image. 
        '''
        select = 'SELECT '+p.cell_x_loc+', '+p.cell_y_loc+' FROM '+p.object_table+' WHERE '+GetWhereClauseForObjects([obKey])
        self.Execute(select)
        res = self.GetResultsAsList()
        assert len(res)==1, "Returned %s objects instead of 1.\n" % len(res)
        return res[0]
    
    
    def GetAllObjectCoordsFromImage(self, imKey):
        ''' 
        Returns a list of lists x, y coordinates for all objects in the given image. 
        '''
        select = 'SELECT '+p.cell_x_loc+', '+p.cell_y_loc+' FROM '+p.object_table+' WHERE '+GetWhereClauseForImages([imKey])
        self.Execute(select)
        return self.GetResultsAsList()


    def GetObjectNear(self, imkey, x, y):
        ''' 
        Returns obKey of the closest object to x, y in an image.
        '''
        delta_x = '(%s - %d)'%(p.cell_x_loc, x)
        delta_y = '(%s - %d)'%(p.cell_y_loc, y)
        dist_clause = '%s*%s + %s*%s'%(delta_x, delta_x, delta_y, delta_y)
        select = 'SELECT '+UniqueObjectClause()+' FROM '+p.object_table+' WHERE '+GetWhereClauseForImages([imkey])+' ORDER BY ' +dist_clause+' LIMIT 1'
        self.Execute(select)
        res = self.GetResultsAsList()
        if len(res) == 0:
            return None
        else:
            return res[0]
    
    
    def GetFullChannelPathsForImage(self, imKey):
        ''' 
        Returns a list of image channel filenames for a particular image
        including the absolute path.
        '''
        assert len(p.image_channel_paths) == len(p.image_channel_files), "Number of image_channel_paths and image_channel_files do not match!"
        
        nChannels = len(p.image_channel_paths)
        select = 'SELECT '
        for i in xrange(nChannels):
            select += p.image_channel_paths[i]+', '+p.image_channel_files[i]+', '
        select = select[:-2] # chop off the last ', '
        select += ' FROM '+p.image_table+' WHERE '+GetWhereClauseForImages([imKey])
        
        self.Execute(select)
        imPaths = self.GetNextResult()
        assert self.GetNextResult() == None, "Query unexpectedly returned more than one result!\n\t"+select
        
        # parse filenames out of results
        filenames = []
        for i in xrange(0,len(p.image_channel_paths*2),2):
            filenames.append( imPaths[i]+'/'+imPaths[i+1] )
        return filenames


    def GetGroupMaps(self):
        '''
        Build dictionary mapping group names and image keys to group keys.
        '''
        groupColNames = {}
        groupMaps = {}
        key_size = p.table_id and 2 or 1
        for group, query in p.groups.items():
            try:
                self.Execute(query)
            except Exception:
                raise Exception, 'Group query failed for group "%s". Check the MySQL syntax in your properties file.'%(group)
            res = self.GetResultsAsList()
            groupColNames[group] = self.GetResultColumnNames()[key_size:]
            d = {}
            for row in res:
                d[row[:key_size]] = row[key_size:]
            groupMaps[group] = d
        return groupMaps, groupColNames
        
    
    def GetFilteredImages(self, filter):
        ''' 
        Returns a list of imKeys from the given filter.
        '''
        try:
            self.Execute(p.filters[filter])
        except Exception, e:
            print e
            raise Exception, 'Filter query failed for filter "%s". Check the MySQL syntax in your properties file.'%(filter)
        return self.GetResultsAsList()
    
    
    def GetColumnNames(self):
        ''' 
        Returns a list of the column names for the specified table.
        '''
        # NOTE: SQLite doesn't like DESCRIBE statements so we do it this way.
        self.Execute('SELECT * FROM %s LIMIT 1'%(p.object_table))
        self.GetResultsAsList()        # ditch the results
        return self.GetResultColumnNames()   # return the column names
            
    
    def GetColnamesForClassifier(self):
        '''
        Returns a list of column names for the object_table excluding 
        those specified in Properties.classifier_ignore_substrings
        '''
        if self.classifierColNames is None:
            # NOTE: SQLite doesn't like DESCRIBE statements so we do it this way.
            self.Execute('SELECT * FROM %s LIMIT 1'%(p.object_table), silent=not verbose)
            self.GetResultsAsList()                   # ditch the results
            col_names = self.GetResultColumnNames()   # get the column names
            self.classifierColNames = list(col_names) # copy them
            
            # automatically ignore ID columns
            if p.table_id:
                self.classifierColNames.remove(p.table_id)
            self.classifierColNames.remove(p.image_id)
            self.classifierColNames.remove(p.object_id)
            
            # treat each classifier_ignore_substring as a regular expression
            # for column names to ignore
            if p.classifier_ignore_substrings:
                self.classifierColNames = [col for col in self.classifierColNames
                                                if not any([re.match('^'+user_exp+'$',col)
                                                       for user_exp in p.classifier_ignore_substrings])]
        print 'Ignoring columns:',[x for x in col_names if x not in self.classifierColNames]
        return self.classifierColNames
    
    
    def GetResultColumnNames(self):
        ''' Returns the column names of the last query on this connection. '''
        connID = threading.currentThread().getName()
        return [x[0] for x in self.cursors[connID].description]

    
    def GetCellDataForClassifier(self, obKey):
        '''
        Returns a list of measurements for the specified object excluding
        those specified in Properties.classifier_ignore_substrings
        '''
        if (self.classifierColNames == None):
            self.GetColnamesForClassifier()
        query = 'SELECT %s FROM %s WHERE %s' %(','.join(self.classifierColNames), p.object_table, GetWhereClauseForObjects([obKey]))
        self.Execute(query, silent=True)
        data = self.GetResultsAsList()
        if len(data) == 0:
            print 'No data for obKey:',obKey
        return numpy.array(data[0])
    
    
    
    
    def CreateSQLiteDB(self):
        '''
        When the user specifies csv files as tables, we create an SQLite DB
        from those tables and do everything else the same.
        '''
        import csv
        # CREATE THE IMAGE TABLE
        # All the ugly code is to establish the type of each column in the table
        # so we can form a proper CREATE TABLE statement.
        f = open(p.image_csv_file, 'r')
        r = csv.reader(f)
        columnLabels = r.next()
        columnLabels = [lbl.strip() for lbl in columnLabels]
        row = r.next()
        rowTypes = {}
        maxLen   = {}   # Maximum string length for each column (if VARCHAR)
        for i in xrange(len(columnLabels)):
            rowTypes[i] = ''
            maxLen[i] = 0 
        while row:
            for i, e in enumerate(row):
                if rowTypes[i]!='FLOAT' and not rowTypes[i].startswith('VARCHAR'):
                    try:
                        x = int(e)
                        rowTypes[i] = 'INT'
                        continue
                    except ValueError: pass
                if not rowTypes[i].startswith('VARCHAR'):
                    try:
                        x = float(e)
                        rowTypes[i] = 'FLOAT'
                        continue
                    except ValueError: pass
                try:
                    x = str(e)
                    maxLen[i] = max(len(x), maxLen[i])
                    rowTypes[i] = 'VARCHAR(%d)'%(maxLen[i])
                except ValueError: 
                    raise Exception, '<ERROR>: Value in table could not be converted to string!'
            try:
                row = r.next()
            except StopIteration: break
        
        # Build the CREATE TABLE statement
        statement = 'CREATE TABLE '+p.image_table+' ('
        statement += ',\n'.join([lbl+' '+rowTypes[i] for i, lbl in enumerate(columnLabels)])
        keys = ','.join([x for x in [p.table_id, p.image_id, p.object_id] if x in columnLabels])
        statement += ',\nPRIMARY KEY (' + keys + ') )'
        f.close()
        
        print 'Creating table:', p.image_table
        self.Execute('DROP TABLE IF EXISTS %s'%(p.image_table))
        self.Execute(statement)
        
        # CREATE THE OBJECT TABLE
        # For the object table we assume that all values are type FLOAT
        # except for the primary keys
        f = open(p.object_csv_file, 'r')
        r = csv.reader(f)
        columnLabels = r.next()
        columnLabels = [lbl.strip() for lbl in columnLabels]
        row = r.next()
        rowTypes = {}
        for i, lbl in enumerate(columnLabels):
            if lbl in [p.table_id, p.image_id, p.object_id]:
                rowTypes[i] = 'INT'
            else:
                rowTypes[i]='FLOAT'
        statement = 'CREATE TABLE '+p.object_table+' ('
        statement += ',\n'.join([lbl+' '+rowTypes[i] for i, lbl in enumerate(columnLabels)])
        keys = ','.join([x for x in [p.table_id, p.image_id, p.object_id] if x in columnLabels])
        statement += ',\nPRIMARY KEY (' + keys + ') )'
        f.close()
    
        print 'Creating table:', p.object_table
        self.Execute('DROP TABLE IF EXISTS '+p.object_table)
        self.Execute(statement)
        
        # POPULATE THE IMAGE TABLE
        f = open(p.image_csv_file, 'r')
        r = csv.reader(f)
        row = r.next() # skip the headers
        row = r.next()
        while row: 
            self.Execute('INSERT INTO '+p.image_table+' VALUES ('+','.join(["'%s'"%(i) for i in row])+')',
                         silent=True)
            try:
                row = r.next()
            except StopIteration:
                break
        f.close()
        
        # POPULATE THE OBJECT TABLE
        f = open(p.object_csv_file, 'r')
        r = csv.reader(f)
        row = r.next() # skip the headers
        row = r.next()
        while row: 
            self.Execute('INSERT INTO '+p.object_table+' VALUES ('+','.join(["'%s'"%(i) for i in row])+')',
                         silent=True)
            try:
                row = r.next()
            except StopIteration:
                break
        f.close()
        
        self.Commit()

        
        



if __name__ == "__main__":

    from TrainingSet import TrainingSet
    import FastGentleBoostingMulticlass
    import MulticlassSQL
    from cStringIO import StringIO
    from DataModel import DataModel
    
    p = Properties.getInstance()
    db = DBConnect.getInstance()
    dm = DataModel.getInstance()

    p.LoadFile('../properties/nirht_test.properties')
    dm.PopulateModel()
    
    print db.GetColnamesForClassifier()
    
#    p.LoadFile('../properties/nirht_local.properties')
#    dm.PopulateModel()
#    
#    print 'group maps:',db.GetGroupMaps()
#    print 'filter "firstten":',db.GetFilteredImages('FirstTen')
#    
#    # Train the classifier
#    imKey = (0,1)
#    nRules = 5
#    trainingSet = TrainingSet(p)
#    # make a training set
#    positives = [(0,1,56), (0,1,72), (0,1,92), (0,1,90), (0,1,88), (0,1,49), (0,1,11)]
#    negatives = [(0,1,i) for i in range(1,95) if i not in [56,72,92,90,88,49,11]]
#    trainingSet.Create(['pos','neg'],[positives, negatives])
#    output = StringIO()
#    print 'Training classifier with '+str(nRules)+' rules...'
#    weaklearners = FastGentleBoostingMulticlass.train(trainingSet.colnames, nRules,
#                                                      trainingSet.label_matrix, 
#                                                      trainingSet.values, output)
#
#    obKeys = dm.GetObjectsFromImage(imKey)
##    imKeysInFilter = db.GetFilteredImages('FirstHundred')
##    obKeys = dm.GetRandomObjects(100,imKeysInFilter)
#    hits = []
#    if obKeys:
#        clNum = 1
#        hits = MulticlassSQL.FilterObjectsFromClassN(clNum, weaklearners, [imKey])
#        
#    print hits
