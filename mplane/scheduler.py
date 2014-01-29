#
# mPlane Protocol Reference Implementation
# Component and Client Job Scheduling
#
# (c) 2013 mPlane Consortium (http://www.ict-mplane.eu)
#          Author: Brian Trammell <brian@trammell.ch>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""
Implements the dynamics of capabilities, specifications, and 
results within the mPlane reference component.

"""

class Service(object):
	"""
	A Service is a binding of some runnable code to an 
	mplane.model.Capability provided by a component.

	To use services with an mPlane scheduler, inherit from 
	mplane.scheduler.Service or one of its subclasses 
	and implement run().

	"""
	def __init__(self, capability):
		super(Service, self).__init__()
		self.capability = capability

	def run(self, specification, check_interrupt):
		"""
		Run this service given a specification which matches the capability.
		This is called by the scheduler, and should be implemented by
		a concrete subclass of Service.

		The implementation should extract its parameters from a given
		mplane.model.Specification, and return its result values in a 
		mplane.model.Result derived therefrom.

		After each row or logically grouped set of rows, the implementation
		should call the check_interrupt function to determine whether it 
		should stop; if this function returns True, the implementation should 
		terminate its processing in an orderly fashion and return its results.

		Each method will be called within its own thread and/or process. 

		"""
		raise NotImplementedError("Cannot instantiate an abstract Service")

class Job(object):
	"""
	A Job is a binding of some running code to an
	mPlane.model.Specification within a component. A Job can
	be thought of as a specific instance of a Service presently
	running, or ready to run at some point in the future.

	"""
	def __init__(self, service, specification):
		super(Job, self).__init__()
		self.service = service
		self.specification = specification
		self.result = None
		self._thread = None
		self._running = False
		self._started_at = None
		self._ended_at = None
		self._interrupt = threading.Event()

	def _run(self):
		self._running = True
		self.result = self.service.run(self.specification, 
									   self._check_interrupt)
		self._running = False

	def _check_interrupt(self):
		return self._interrupt.is_set()

	def _schedule_now(self):
		pass

	def schedule(self):
		"""
		Schedule this job to run.

 		"""
 		start = self.specification.get_parameter_value("start")
 		end = self.specification.get_parameter_value("end")

 		# calculate a delay
 		if start.isinstance(datetime):
			delay = start - datetime.utcnow()
			if end.isinstance(datetime):
				duration = end - start
		elif ((start is mplane.model.time_now) or 
	     	  (start is mplane.model.time_whenever):
	     	# treat now and whenever as immediate start
	     	# revisit this if we actually want to do prioritization
			delay = timedelta()
			if end.isinstance(datetime):
				duration = end - start

 		if delay.total_seconds() > 0:
 			threading.Timer(delay.total_seconds(), self._schedule_now)

 		else:
 			self._schedule_now()

	def interrupt(self):
		"""
		Interrupt this job.

		"""
		self._interrupt.set()
