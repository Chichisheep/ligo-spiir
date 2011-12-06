import sys, os, copy, math
import subprocess, socket, tempfile
from glue import pipeline, lal
from glue.ligolw import utils, lsctables, array

###############################################################################
# environment utilities
###############################################################################

def which(prog):
	which = subprocess.Popen(['which',prog], stdout=subprocess.PIPE)
	out = which.stdout.read().strip()
	if not out: 
		print >>sys.stderr, "ERROR: could not find %s in your path, have you built the proper software and source the proper env. scripts?" % (prog,prog)
		raise ValueError 
	return out

def log_path():
	host = socket.getfqdn()
	#FIXME add more hosts as you need them
	if 'cit' in host or 'caltech.edu' in host: return '/usr1/' + os.environ['USER']
	if 'phys.uwm.edu' in host: return '/localscratch/' + os.environ['USER']
	if 'aei.uni-hannover.de' in host: return '/local/user/' + os.environ['USER']
	if 'phy.syr.edu' in host: return '/usr1/' + os.environ['USER']


###############################################################################
# DAG class
###############################################################################

class bank_DAG(pipeline.CondorDAG):

	def __init__(self, name, logpath = log_path()):
		self.basename = name
		tempfile.tempdir = logpath
		tempfile.template = self.basename + '.dag.log.'
		logfile = tempfile.mktemp()
		fh = open( logfile, "w" )
		fh.close()
		pipeline.CondorDAG.__init__(self,logfile)
		self.set_dag_file(self.basename)
		self.jobsDict = {}
		self.node_id = 0
		self.output_cache = []

	def add_node(self, node):
		node.set_retry(3)
		self.node_id += 1
		node.add_macro("macroid", self.node_id)
		node.add_macro("macronodename", node.get_name())
		pipeline.CondorDAG.add_node(self, node)

	def write_cache(self):
		out = self.basename + ".cache"
		f = open(out,"w")
		for c in self.output_cache:
			f.write(str(c)+"\n")
		f.close()


###############################################################################
# Utility functions
###############################################################################

def num_bank_files(cachedict):
	ifo = cachedict.keys()[0]
	f = open(cachedict[ifo],'r')
	cnt = 0
	for l in f:
		cnt+=1
	f.close()
	return cnt

def parse_cache_str(instr):
	dictcache = {}
	if instr is None: return dictcache
	for c in instr.split(','):
		ifo = c.split("=")[0]
		cache = c.replace(ifo+"=","")
		dictcache[ifo] = cache
	return dictcache

def build_bank_string(cachedict, numbanks = [2], maxjobs = None):
	numfiles = num_bank_files(cachedict)
	filedict = {}
	cnt = 0
	job = 0
	for ifo in cachedict:
		filedict[ifo] = open(cachedict[ifo],'r')
	
	loop = True
	while cnt < numfiles:
		job += 1
		if maxjobs is not None and job > maxjobs:
			break
		position = int(float(cnt) / numfiles * len(numbanks))
		c = ''
		for i in range(numbanks[position]):
			cnt += 1
			for ifo, f in filedict.items():
				if cnt < numfiles:
					c += '%s:%s,' % (ifo, lal.CacheEntry(f.readline()).path())
				else:
					break
		c = c.strip(',')
		yield c

def get_independence_factor(bank_cache, ifo = "H1", maxjobs = None):
	dof = 0.0
	num_tmps = 0
	for cnt, s in enumerate(build_bank_string(bank_cache)):
		if maxjobs is not None and cnt > maxjobs:
			break
		fname = parse_banks(s)[ifo][0]
		lw = utils.load_filename(fname, verbose = False).childNodes[0]
		for node in (node for node in lw.childNodes if node.tagName == 'LIGO_LW'):
			dof += array.get_array(node, 'sum_of_squares_weights').array.sum()
		num_tmps += len(lsctables.table.get_table(lw, lsctables.SnglInspiralTable.tableName))
		print >>sys.stderr, "processing bank %d\r" % (cnt,),
	return dof / num_tmps

def parse_banks(bank_string):
	out = {}
	for b in bank_string.split(','):
		ifo, bank = b.split(':')
		out.setdefault(ifo, []).append(bank)
	return out

