import os
from dotenv import load_dotenv
from pathlib import Path
import json
import time
import functools
from datetime import datetime, timedelta

from os import F_OK, W_OK
from stat import S_IREAD, S_IRGRP, S_IROTH, S_IWUSR
import uuid
from miros import Factory
from miros import signals, Event, return_status
from miros import pp
import random
from miros_rabbitmq.network import PikaTopicPublisher

from collections import namedtuple
import ipaddress
import socket
import subprocess
import netifaces

env_path = Path('.') / '.env'
load_dotenv()

class EnvContractBroken(Exception):
  pass

class LoadEnvironmentalVariables():
  def __init__(self):
    if os.getenv('RABBIT_PASSWORD') is None:
      load_dotenv()  # climb out of this dir to find dir containing .env file

    # What this package needs from the .env file for this software to run.
    # if the file is missing any of this information, crash now
    if not os.getenv('RABBIT_PASSWORD'):
      raise EnvContractBroken('RABBIT_PASSWORD is missing from your .env file')

    if not os.getenv('RABBIT_USER'):
      raise EnvContractBroken('RABBIT_USER is missing from your .env file')

    if not os.getenv('RABBIT_PORT'):
      raise EnvContractBroken('RABBIT_PORT is missing from your .env file')

    if not os.getenv('RABBIT_HEARTBEAT_INTERVAL'):
      raise EnvContractBroken('RABBIT_HEARTBEAT_INTERVAL is missing from your .env file')

    if not os.getenv('CONNECTION_ATTEMPTS'):
      raise EnvContractBroken('CONNECTION_ATTEMPTS is missing from your .env file')

    if not os.getenv('MESH_ENCRYPTION_KEY'):
      raise EnvContractBroken('MESH_ENCRYPTION_KEY is missing from your .env file')

    if not os.getenv('SNOOP_TRACE_ENCRYPTION_KEY'):
      raise EnvContractBroken('SNOOP_TRACE_ENCRYPTION_KEY is missing from your .env file')

    if not os.getenv('SNOOP_SPY_ENCRYPTION_KEY'):
      raise EnvContractBroken('SNOOP_SPY_ENCRYPTION_KEY is missing from your .env file')

    # if not os.getenv('SNOOP_BOB'):
    #   raise EnvContractBroken('SNOOP_BOB is missing from your .env file')

class RabbitHelper():
  def __init__(self):
    '''Create a scout memory interface'''
    LoadEnvironmentalVariables()
    self.rabbit_user = os.getenv('RABBIT_USER')
    self.rabbit_password = os.getenv('RABBIT_PASSWORD')
    self.rabbit_port = os.getenv('RABBIT_PORT')
    self.rabbit_heartbeat_interval = os.getenv('RABBIT_HEARTBEAT_INTERVAL')
    self.connection_attempts = os.getenv('CONNECTION_ATTEMPTS')

  def make_amqp_url(self,
               ip_address,
               rabbit_user=None,
               rabbit_password=None,
               rabbit_port=None,
               connection_attempts=None,
               heartbeat_interval=None):
    '''Make a RabbitMq url.

      **Example**:

      .. code-block:: python

        amqp_url = \\
          self.make_amqp_url(
              ip_address=192.168.1.1,    # only mandatory argument
              rabbit_user='peter',       # if any of the following args not given
              rabbit_password='rabbit',  # the .env file will be used
              connection_attempts='3',
              heartbeat_interval='3600')

        print(amqp_url)  # =>
          'amqp://bob:dobbs@192.168.1.1:5672/%2F?connection_attempts=3&heartbeat_interval=3600'

    '''
    if rabbit_port is None:
      rabbit_port = self.rabbit_port
    if connection_attempts is None:
      connection_attempts = self.connection_attempts
    if heartbeat_interval is None:
      heartbeat_interval = self.rabbit_heartbeat_interval

    amqp_url = \
      "amqp://{}:{}@{}:{}/%2F?connection_attempts={}&heartbeat_interval={}".format(
          self.rabbit_user,
          self.rabbit_password,
          ip_address,
          rabbit_port,
          connection_attempts,
          heartbeat_interval)
    return amqp_url

class JsonCache():
  default_structure = """{
  "live" : {
    "addresses": [],
    "amqp_urls": []
  },
  "dead" : {
    "addresses": [],
    "amqp_urls": []
  },
  "time_out_in_minutes": 30
}
"""

class MirosRabbitMQConnections():
  default_json_structure = """{
  "live" : {
    "addresses": [],
    "amqp_urls": []
  },
  "dead" : {
    "addresses": [],
    "amqp_urls": []
  },
  "time_out_in_minutes": 30
}
"""

  def __init__(self, cache_file_path=None):
    '''Create a scout memory interface'''
    LoadEnvironmentalVariables()
    self.rabbit_user = os.getenv('RABBIT_USER')
    self.rabbit_password = os.getenv('RABBIT_PASSWORD')
    self.rabbit_port = os.getenv('RABBIT_PORT')
    self.rabbit_heartbeat_interval = os.getenv('RABBIT_HEARTBEAT_INTERVAL')
    self.connection_attempts = os.getenv('CONNECTION_ATTEMPTS')

  def make_amqp_url(self,
               ip_address,
               rabbit_user=None,
               rabbit_password=None,
               rabbit_port=None,
               connection_attempts=None,
               heartbeat_interval=None):
    '''Make a RabbitMq url.

      **Example**:

      .. code-block:: python

        amqp_url = \\
          self.make_amqp_url(
              ip_address=192.168.1.1,    # only mandatory argument
              rabbit_user='peter',       # if any of the following args not given
              rabbit_password='rabbit',  # the .env file will be used
              connection_attempts='3',
              heartbeat_interval='3600')

        print(amqp_url)  # =>
          'amqp://bob:dobbs@192.168.1.1:5672/%2F?connection_attempts=3&heartbeat_interval=3600'

    '''
    if rabbit_port is None:
      rabbit_port = self.rabbit_port
    if connection_attempts is None:
      connection_attempts = self.connection_attempts
    if heartbeat_interval is None:
      heartbeat_interval = self.rabbit_heartbeat_interval

    amqp_url = \
      "amqp://{}:{}@{}:{}/%2F?connection_attempts={}&heartbeat_interval={}".format(
          rabbit_user,
          rabbit_password,
          ip_address,
          rabbit_port,
          connection_attempts,
          heartbeat_interval)
    return amqp_url

  def addesses_and_amqp_urls_for(self, automatic=None, manual=None, live=None, dead=None):
    '''Get the addresses and amqp_urls for node

    The contract rules for this method are:
      automatic and not manual or not automatic and manual
      if manual then
        live and not dead or not live and dead
    '''

    assert((automatic and not manual) or (not automatic and manual))
    if manual:
      assert((live and not dead) or(not live and dead))

    if automatic:
      addresses = self.dict['nodes']['automatic']['addresses']
      amqp_urls = self.dict['nodes']['automatic']['amqp_urls']
    elif manual:
      if live:
        addresses = self.dict['nodes']['manual']['live']['addresses']
        amqp_urls = self.dict['nodes']['manual']['live']['amqp_urls']
      elif dead:
        addresses = self.dict['nodes']['manual']['dead']['addresses']
        amqp_urls = self.dict['nodes']['manual']['dead']['amqp_urls']
    return (addresses, amqp_urls)

  def append(self, address, amqp_url, automatic=None, manual=None, live=None, dead=None):
    '''Append an address or amqp_url to a node'''

    changed = False
    addresses, amqp_urls = self.addesses_and_amqp_urls_for(automatic, manual, live, dead)

    if address is not None and (address in addresses) is False:
      addresses.append(address)
      changed |= True
    if amqp_url is not None and (amqp_url in amqp_urls) is False:
      amqp_urls.append(amqp_url)
      changed |= True
    if changed:
      self.write()

  def in_cache(self, address, amqp_url, automatic=None, manual=None, live=None, dead=None):
    '''Is an address or amqp_url in a given cache?'''
    addresses, amqp_urls = self.addesses_and_amqp_urls_for(automatic, manual, live, dead)
    in_cache = False

    if address in addresses:
      in_cache |= True

    if amqp_url in amqp_urls:
      in_cache |= True

    return in_cache

  def in_automatic_cache(self, address, amqp_url):
    '''Is an address or amqp_url in the automatic cache?'''
    in_cache_fn = functools.partial(self.in_cache, automatic=True)
    result = in_cache_fn(address, amqp_url)
    return result

  def in_manual_live_cache(self, address, amqp_url):
    '''Is an address or amqp_url in the manual live cache?'''
    in_cache_fn = functools.partial(self.in_cache, manual=True, live=True)
    result = in_cache_fn(address, amqp_url)
    return result

  def in_manual_dead_cache(self, address, amqp_url):
    '''Is an address or amqp_url in the manual dead cache?'''
    in_cache_fn = functools.partial(self.in_cache, manual=True, dead=True)
    result = in_cache_fn(address, amqp_url)
    return result

  def remove(self, address, amqp_url, automatic=None, manual=None, live=None, dead=None):
    '''Remove an address or amqp_url to a node'''
    changed = False
    addresses, amqp_urls = self.addesses_and_amqp_urls_for(automatic, manual, live, dead)

    if address is not None and (address in addresses) is False:
      addresses.remove(address)
      changed |= True
    if amqp_url is not None and (amqp_url in amqp_urls) is False:
      amqp_urls.remove(amqp_url)
      changed |= True
    if changed:
      self.write()

  def append_automatic(self, address=None, amqp_url=None):
    '''Append an address or amqp_url to the automatic node'''
    append = functools.partial(self.append, automatic=True)
    append(address, amqp_url)

  def append_manual_live(self, address=None, amqp_url=None):
    '''Append an address or amqp_url to a manual live node

    If this address and or amqp_url exists in the manual dead node, it is
    removed'''
    append_to_live = functools.partial(self.append, manual=True, live=True)
    remove_from_dead = functools.partial(self.remove, manual=True, dead=True)
    append_to_live(address, amqp_url)
    remove_from_dead(address, amqp_url)

  def append_manual_dead(self, address=None, amqp_url=None):
    '''Append an address or amqp_url to a manual dead node

    If this address and or amqp_url exists in the manual live node, it is
    removed'''
    append_to_dead = functools.partial(self.append, manual=True, dead=True)
    remove_from_live = functools.partial(self.remove, manual=True, live=True)
    append_to_dead(address, amqp_url)
    remove_from_live(address, amqp_url)

  #def write(self, addresses=None, ampq_urls=None):
  #  '''Write the cache file to disk'''
  #  with open(self.cache_file_name, "w") as f:
  #    f.write(json.dumps(self.dict, sort_keys=True, indent=2))

  def remove_all_automatic(self):
    '''Remove all automatic addresses and amqp_urls from the automatic node'''
    automatic_nodes = self.dict['nodes']['automatic']
    automatic_nodes['addresses'] = []
    automatic_nodes['amqp_urls'] = []
    #self.write()

  def remove_all_dead(self):
    '''Remove all automatic addresses and amqp_urls from the manual dead node'''
    automatic_nodes = self.dict['nodes']['manual']['dead']
    automatic_nodes['addresses'] = []
    automatic_nodes['amqp_urls'] = []
    #self.write()

  def destroy(self):
    '''Delete the cache file all addresses and amqp_urls will be destroyed'''
    self.dict = {}
    os.remove(self.cache_file_name)

class CacheFile(Factory):
  def __init__(self, name, file_path, system_read_signal_name=None):
    super().__init__(name)
    self.file_path = file_path

    self.json = None
    self.created_at = None
    self.last_modified = None

    if system_read_signal_name is None:
      self.system_read_signal_name = signals.CACHE
    else:
      self.system_read_signal_name = system_read_signal_name

  def exists(self):
    return os.access(self.file_path, F_OK)

  def writeable(self):
    return os.access(self.file_path, W_OK)

  def write_access_off(self):
    os.chmod(self.file_path, S_IREAD | S_IRGRP | S_IROTH)

  def write_access_on(self):
    os.chmod(self.file_path, S_IWUSR | S_IREAD | S_IRGRP | S_IROTH)

  def temp_file_name(self):
    return "temp_file_{}".format(uuid.uuid4().hex.upper()[0:12])

  def expired(self):
    last_modified = datetime.fromtimestamp(self.last_modified)
    duration = datetime.now() - last_modified
    try:
      timeout = timedelta(minutes=self.dict['time_out_in_minutes'])
      is_expired = True if timeout == timedelta(0) else False
      if duration > timeout:
        is_expired = True
    except:
      is_expired = False
    return is_expired

CacheReadPayload = \
  namedtuple('CacheReadPayload',
    ['dict', 'last_modified', 'created_at', 'expired', 'file_name'])

CacheWritePayload = \
  namedtuple('CacheWritePayload', ['json'])

class CacheFileChart(CacheFile):
  def __init__(self, file_path=None, live_trace=None, live_spy=None):
    if file_path is None:
      file_path = str(Path('.') / '.miros_rabbitmq_cache.json')
    self.file_name = os.path.basename(file_path)
    super().__init__(self.file_name, file_path=file_path)


    self.file_access_waiting = self.create(state='file_access_waiting'). \
        catch(signal=signals.ENTRY_SIGNAL, handler=self.faw_entry). \
        catch(signal=signals.CACHE_FILE_READ, handler=self.faw_CACHE_FILE_READ). \
        catch(signal=signals.CACHE_FILE_WRITE, handler=self.faw_CACHE_FILE_WRITE). \
        catch(signal=signals.faw_CACHE_DESTROY, handler=self.faw_CACHE_DESTROY). \
        catch(signal=signals.cache_file_read, handler=self.faw_cache_file_read). \
        catch(signal=signals.cache_file_write, handler=self.faw_cache_file_write). \
        to_method()

    self.file_accessed = self.create(state='file_accessed'). \
        catch(signal=signals.ENTRY_SIGNAL, handler=self.fa_entry). \
        catch(signal=signals.EXIT_SIGNAL, handler=self.fa_exit). \
        to_method()

    self.file_read = self.create(state='file_read'). \
        catch(signal=signals.ENTRY_SIGNAL, handler=self.fr_entry). \
        catch(signal=signals.read_successful, handler=self.fr_read_successful). \
        to_method()

    self.file_write = self.create(state='file_write'). \
        catch(signal=signals.ENTRY_SIGNAL, handler=self.fw_entry). \
        catch(signal=signals.write_successful, handler=self.fw_write_successful). \
        to_method()

    self.nest(self.file_access_waiting, parent=None). \
        nest(self.file_accessed, parent=self.file_access_waiting). \
        nest(self.file_read, parent=self.file_accessed). \
        nest(self.file_write, parent=self.file_accessed)

    if live_trace is None:
      live_trace = False
    else:
      live_trace = live_trace

    if live_spy is None:
      live_spy = False
    else:
      live_spy = live_spy

    self.live_trace = live_trace
    self.live_spy = live_spy
    self.start_at(self.file_access_waiting)
    #self.post_fifo(Event(signal=signals.CACHE_FILE_READ))

  @staticmethod
  def timeout(times):
    top_timeout = 0.1 + (1.2**times)
    top_timeout = 5 if top_timeout > 5 else top_timeout
    _timeout = random.uniform(0.001, top_timeout)
    return _timeout

  @staticmethod
  def faw_entry(cache, e):
    '''The file_access_waiting state ENTRY_SIGNAL event handler'''
    cache.subscribe(Event(signal=signals.CACHE_FILE_READ))
    cache.subscribe(Event(signal=signals.CACHE_FILE_WRITE))

    # check if file exists, if not make it with nothing in it
    if not os.path.isfile(cache.file_path):
      open(cache.file_path, 'a').close()
    return return_status.HANDLED

  @staticmethod
  def faw_CACHE_FILE_READ(cache, e):
    '''The file_access_waiting state global CACHE_FILE_READ event handler'''
    cache.post_fifo(Event(signal=signals.cache_file_read, payload={'times': 0}))
    return return_status.HANDLED

  @staticmethod
  def faw_CACHE_FILE_WRITE(cache, e):
    '''The file_access_waiting state global CACHE_FILE_WRITE event handler'''
    cache.json = e.payload.json  # kept for debugging
    cache.dict = json.load(open(cache.file_path, 'r'))
    assert('time_out_in_minutes' in cache.dict)
    cache.post_fifo(Event(signal=signals.cache_file_write, payload={'times': 0, 'dict': cache.dict}))
    return return_status.HANDLED

  @staticmethod
  def faw_CACHE_DESTROY(cache, e):
    '''The file_access_waiting state global faw_CACHE_DESTROY event handler'''
    # write empty cache with a timeout of 0 to meet our contract, yet to cause a
    # timeout
    cache.post_fifo(Event(signal=signals.cache_file_write),
        payload=CacheWritePayload(json=json.dumps({'time_out_in_minutes': 0})))
    return return_status.HANDLED

  @staticmethod
  def faw_cache_file_read(cache, e):
    '''The file_access_waiting state private cache_file_read event handler'''
    if cache.writeable():
      status = cache.trans(cache.file_read)
    else:
      # wait a short amount of time then try again
      times = e.payload['times']
      timeout = random.uniform(0.001, cache.timeout(times))
      cache.post_fifo(Event(signal=signals.cache_file_read, payload={'times': times + 1}),
        period=timeout,
        times=1,
        deferred=True)
      status = return_status.HANDLED
    return status

  @staticmethod
  def faw_cache_file_write(cache, e):
    '''The file_access_waiting state private cache_file_write event handler'''
    status = return_status.HANDLED
    if cache.writeable():
      status = cache.trans(cache.file_write)
    else:
      times = e.payload['times']
      timeout = random.uniform(0.001, cache.timeout(times))
      # wait a short amount of time then try again sending the same payload
      cache.post_fifo(
        Event(signal=signals.cache_file_write, payload={'times': times + 1, 'dict': cache.dict}),
        period=timeout,
        times=1,
        deferred=True)
    return status

  @staticmethod
  def fa_entry(cache, e):
    '''The file_accessed state ENTRY_SIGNAL event handler'''
    cache.write_access_off()
    return return_status.HANDLED

  @staticmethod
  def fa_exit(cache, e):
    '''The file_accessed state EXIT_SIGNAL event handler'''
    cache.write_access_on()
    return return_status.HANDLED

  @staticmethod
  def fr_entry(cache, e):
    '''The file_read state ENTRY_SIGNAL event handler'''
    cache.dict = json.load(open(cache.file_path, 'r'))
    cache.json = json.dumps(cache.dict, sort_keys=True, indent=2)
    cache.last_modified = os.path.getmtime(cache.file_path)
    cache.created_at = time.ctime(os.path.getctime(cache.file_path))
    payload = CacheReadPayload(
      dict=cache.dict,
      last_modified=cache.last_modified,
      created_at=cache.created_at,
      expired=cache.expired(),
      file_name = cache.file_name
    )
    cache.publish(Event(signal=signals.CACHE, payload=payload))
    cache.post_lifo(Event(signal=signals.read_successful))
    pp(cache.json)
    return return_status.HANDLED

  @staticmethod
  def fr_read_successful(cache, e):
    return cache.trans(cache.file_access_waiting)

  @staticmethod
  def fw_write_successful(cache, e):
    return cache.trans(cache.file_access_waiting)

  @staticmethod
  def fw_entry(cache, e):
    '''The file_write state ENTRY_SIGNAL event handler'''
    status = return_status.HANDLED
    temp_file = cache.temp_file_name()
    f = open(temp_file, "w")
    f.write(cache.json)
    # write the file to disk
    f.flush()
    os.fsync(f.fileno())
    f.close()
    # atomic replacement of cache.file_name with temp_file
    os.rename(temp_file, cache.file_path)
    cache.post_lifo(Event(signal=signals.write_successful))
    return status


class PikaTopicPublisherMaker():
  '''A class which removes as much of the tedium from building a pika producer as is possible.'''
  HEARTBEAT_INTERVAL_SEC = 3600
  CALLBACK_TEMPO = 0.1
  CONNECTION_ATTEMPTS = 3

  def __init__(self,
                ip_address,
                routing_key,
                exchange_name,
                connection_attempts=None,
                heartbeat_interval=None,
                callback_tempo=None):

    LoadEnvironmentalVariables()

    self.ip_address = ip_address
    self.routing_key = routing_key
    self.exchange_name = exchange_name

    self.rabbit_user = os.getenv('RABBIT_USER')
    self.rabbit_password = os.getenv('RABBIT_PASSWORD')
    self.rabbit_port = os.getenv('RABBIT_PORT')
    self.encryption_key = os.getenv('MESH_ENCRYPTION_KEY')

    # contract for this make class to work
    assert(self.rabbit_user)
    assert(self.rabbit_password)
    assert(self.rabbit_port)
    assert(self.encryption_key)

    if heartbeat_interval is None:
      self.heartbeat_interval = os.getenv('RABBIT_HEARTBEAT_INTERVAL')
      if not self.heartbeat_interval:
        self.heartbeat_interval = PikaTopicPublisherMaker.HEARTBEAT_INTERVAL_SEC
    else:
      self.heartbeat_interval = heartbeat_interval

    if callback_tempo is None:
      self.callback_tempo = PikaTopicPublisherMaker.CALLBACK_TEMPO
    else:
      self.callback_tempo = callback_tempo

    if connection_attempts is None:
      connection_attempts = PikaTopicPublisherMaker.CONNECTION_ATTEMPTS

    self.rabbit_helper = RabbitHelper()
    self.amqp_url = self.rabbit_helper.make_amqp_url(
        ip_address=self.ip_address,
        rabbit_user=self.rabbit_user,
        rabbit_password=self.rabbit_password,
        rabbit_port=self.rabbit_port,
        connection_attempts=connection_attempts,
        heartbeat_interval=heartbeat_interval)

    self.producer = PikaTopicPublisher(
        amqp_url = self.amqp_url,
        routing_key = self.routing_key,
        publish_tempo_sec = self.callback_tempo,
        exchange_name = self.exchange_name,
        encryption_key = self.encryption_key)

AMQPConsumerCheckPayload = \
  namedtuple('AMQPConsumerCheckPayload',
    ['ip_address', 'result', 'routing_key', 'exchange_name'])

class RabbitConsumerScout(Factory):
  CONNECTION_ATTEMPTS    = 1

  SCOUT_TEMPO_SEC        = 0.01
  SCOUT_TIMEOUT_SEC      = 0.5

  def __init__(self, ip_address, routing_key, exchange_name):
    super().__init__(ip_address)

    self.ip_address = ip_address
    self.routing_key = routing_key
    self.exchange_name = exchange_name

  def get_amqp_consumer_check_payload(self, result):
    return AMQPConsumerCheckPayload(
      ip_address=self.ip_address,
      result=result,
      routing_key=self.routing_key,
      exchange_name=self.exchange_name)

class RabbitConsumerScoutChart(RabbitConsumerScout):
  def __init__(self, ip_address, routing_key, exchange_name, live_trace=None, live_spy=None):
    super().__init__(ip_address, routing_key, exchange_name)

    self.search = self.create(state='search'). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.search_entry). \
      catch(signal=signals.REFACTOR_SEARCH, handler=self.search_refactor_search). \
      catch(signal=signals.AMQP_CONSUMER_CHECK, handler=self.search_AMPQ_CONSUMER_CHECK).  \
      catch(signal=signals.INIT_SIGNAL, handler=self.search_init). \
      to_method()

    self.producer_thread_engaged = self.create(state='producer_thread_engaged'). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.producer_thread_engaged_entry). \
      catch(signal=signals.EXIT_SIGNAL, handler=self.producer_thread_engaged_exit). \
      catch(signal=signals.try_to_connect_to_consumer, handler=self.producer_try_to_contact_consumer). \
      catch(signal=signals.consumer_test_complete, handler=self.producer_thread_engaged_consumer_test_complete). \
      to_method()

    self.producer_post_and_wait = self.create(state='producer_post_and_wait'). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.producer_post_and_wait_entry). \
      to_method()

    self.amqp_consumer_server_found = self.create(state="amqp_consumer_server_found"). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.amqp_consumer_server_found_entry).  \
      to_method()

    self.no_amqp_consumer_server_found = self.create(state="no_amqp_consumer_server_found"). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.no_amqp_consumer_server_found_entry). \
      to_method()

    self.nest(self.search, parent=None). \
      nest(self.producer_thread_engaged, parent=self.search). \
      nest(self.producer_post_and_wait, parent=self.producer_thread_engaged). \
      nest(self.amqp_consumer_server_found, parent=self.search). \
      nest(self.no_amqp_consumer_server_found, parent=self.search)

    if live_trace is None:
      live_trace = False
    else:
      live_trace = live_trace

    if live_spy is None:
      live_spy = False
    else:
      live_spy = live_spy

    self.live_trace = live_trace
    self.live_spy = live_spy
    self.start_at(self.search)

  @staticmethod
  def search_entry(scout, e):
    status = return_status.HANDLED
    scout.producer = PikaTopicPublisherMaker(
        ip_address=scout.ip_address,
        routing_key=scout.routing_key,
        exchange_name=scout.exchange_name,
        connection_attempts=RabbitConsumerScout.CONNECTION_ATTEMPTS,
        callback_tempo=RabbitConsumerScout.SCOUT_TEMPO_SEC).producer
    scout.subscribe(Event(signals.REFACTOR_SEARCH))
    scout.subscribe(Event(signal=signals.AMQP_CONSUMER_CHECK))
    return status

  @staticmethod
  def search_AMPQ_CONSUMER_CHECK(scout, e):
    status = return_status.HANDLED
    if scout.live_trace or scout.live_spy:
      pp(e.payload)
    return status

  @staticmethod
  def search_refactor_search(scout, e):
    status = return_status.HANDLED
    if 'ip_address' in e.payload and scout.name is e.payload['ip_address']:
      for item in ['routing_key', 'exchange_name']:
        if item in e.payload:
          setattr(scout, item, e.payload[item])
    status = scout.trans(scout.search)
    return status

  @staticmethod
  def search_init(scout, e):
    return scout.trans(scout.producer_thread_engaged)

  @staticmethod
  def producer_thread_engaged_entry(scout, e):
    status = return_status.HANDLED
    scout.producer.start_thread()
    scout.post_fifo(Event(
      signal=signals.try_to_connect_to_consumer),
      times=1,
      period=0.1,
      deferred=True)
    return status

  @staticmethod
  def producer_try_to_contact_consumer(scout, e):
    status = scout.trans(scout.producer_post_and_wait)
    return status

  @staticmethod
  def producer_thread_engaged_exit(scout, e):
    status = return_status.HANDLED
    scout.cancel_events(
      Event(signal=signals.try_to_connect_to_consumer))
    scout.producer.stop_thread()
    return status

  @staticmethod
  def producer_thread_engaged_consumer_test_complete(scout, e):
    status = return_status.HANDLED
    if scout.producer.connect_error:
      status = scout.trans(scout.no_amqp_consumer_server_found)
    else:
      status = scout.trans(scout.amqp_consumer_server_found)
    return status

  @staticmethod
  def producer_post_and_wait_entry(scout, e):
    status = return_status.HANDLED
    # send a unexpected message to make it harder to decrypt
    scout.producer.post_fifo(uuid.uuid4().hex.upper()[0:12])
    scout.post_fifo(
      Event(signal=signals.consumer_test_complete),
      times=1,
      period=RabbitConsumerScout.SCOUT_TIMEOUT_SEC,
      deferred=True
    )
    return status

  @staticmethod
  def amqp_consumer_server_found_entry(scout, e):
    status = return_status.HANDLED
    payload = scout.get_amqp_consumer_check_payload(True)
    scout.publish(Event(signal=signals.AMQP_CONSUMER_CHECK, payload=payload))
    return status

  @staticmethod
  def no_amqp_consumer_server_found_entry(scout, e):
    status = return_status.HANDLED
    payload = scout.get_amqp_consumer_check_payload(False)
    scout.publish(Event(signal=signals.AMQP_CONSUMER_CHECK, payload=payload))
    return status

class Attribute():
  def __init__(self):
    pass

RecceNode = namedtuple('RecceNode', ['searched', 'result', 'scout'])

class LanRecce(Factory):
  def __init__(self, routing_key, exchange_name, name=None,):
    if name is None:
      name = 'lan_recce_chart'
    super().__init__(name)
    self.my  = Attribute()
    self.other = Attribute()
    self.routing_key = routing_key
    self.exchange_name = exchange_name
    self.candidates = None

  def get_ipv4_network(self):
    ip_address = LanRecce.get_working_ip_address()
    netmask    = self.netmask_on_this_machine()
    inet4      = ipaddress.ip_network(ip_address + '/' + netmask, strict=False)
    return inet4

  def netmask_on_this_machine(self):
    interfaces = [interface for interface in netifaces.interfaces()]
    local_netmask = None
    working_address = LanRecce.get_working_ip_address()
    for interface in interfaces:
      interface_network_types = netifaces.ifaddresses(interface)
      if netifaces.AF_INET in interface_network_types:
        if interface_network_types[netifaces.AF_INET][0]['addr'] == working_address:
          local_netmask = interface_network_types[netifaces.AF_INET][0]['netmask']
          break
    return local_netmask

  def ping_to_fill_arp_table(self):
    linux_cmd = 'ping -b {}'
    inet4 = self.get_ipv4_network()

    if inet4.num_addresses <= 256:
      broadcast_address = inet4[-1]
      fcmd = linux_cmd.format(broadcast_address)
      fcmd_as_list = fcmd.split(" ")
      try:
        ps = subprocess.Popen(fcmd_as_list, stdout=open(os.devnull, "wb"))
        ps.wait(2)
      except:
        ps.kill()
    return

  def candidate_ip_addresses(self):
    lan_ip_addresses = []
    a = set(self.ip_addresses_on_lan())
    b = set(self.ip_addresses_on_this_machine())
    c = set([LanRecce.get_working_ip_address()])
    candidates = list(a - b ^ c)
    inet4 = self.get_ipv4_network()
    for host in inet4.hosts():
      shost = str(host)
      if shost in candidates:
        lan_ip_addresses.append(shost)
    return lan_ip_addresses

  def ip_addresses_on_lan(self):
    wsl_cmd   = 'cmd.exe /C arp.exe -a'
    linux_cmd = 'arp -a'

    grep_cmd = 'grep -Po 192\.\d+\.\d+\.\d+'
    candidates = []

    for cmd in [wsl_cmd, linux_cmd]:
      cmd_as_list = cmd.split(" ")
      grep_as_list = grep_cmd.split(" ")
      output = ''
      try:
        ps = subprocess.Popen(cmd_as_list, stdout=subprocess.PIPE)
        output = subprocess.check_output(grep_as_list, stdin=ps.stdout, timeout=0.5)
        ps.wait()
        if output is not '':
          candidates = output.decode('utf-8').split('\n')
          if len(candidates) > 0:
            break
      except:
        # our windows command did not work on Linux
        pass
    return list(filter(None, candidates))

  def ip_addresses_on_this_machine(self):
    interfaces = [interface for interface in netifaces.interfaces()]
    local_ip_addresses = []
    for interface in interfaces:
      interface_network_types = netifaces.ifaddresses(interface)
      if netifaces.AF_INET in interface_network_types:
        ip_address = interface_network_types[netifaces.AF_INET][0]['addr']
        local_ip_addresses.append(ip_address)
    return local_ip_addresses

  @staticmethod
  def get_working_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
      s.connect(('10.255.255.255', 1))
      ip = s.getsockname()[0]
    except:
      ip = '127.0.0.1'
    finally:
      s.close()
    return ip

RecceCompletePayload = \
  namedtuple('RecceCompletePayload', ['other_addresses', 'my_address'])

class LanRecceChart(LanRecce):
  ARP_TIME_OUT_SEC = 2.0

  def __init__(self, routing_key, exchange_name, live_trace=None, live_spy=None, arp_timeout_sec=None):

    super().__init__(routing_key, exchange_name, name='lan_recce_chart')

    if arp_timeout_sec is None:
      self.arp_timeout_sec = LanRecceChart.ARP_TIME_OUT_SEC

    self.private_search = self.create(state="private_search"). \
      catch(signals.ENTRY_SIGNAL, handler=self.private_search_entry). \
      catch(signals.RECCE_LAN, handler=self.private_search_RECCE_LAN). \
      catch(signals.recce_lan, handler=self.private_recce_lan). \
      catch(signal=signals.LAN_RECCE_COMPLETE, handler=self.private_search_RECCE_COMPLETE). \
      to_method()

    self.lan_recce = self.create(state='recce'). \
      catch(signals.RECCE_LAN, handler=self.lan_recce_RECCE_LAN). \
      catch(signals.INIT_SIGNAL, handler=self.lan_recce_init). \
      catch(signals.EXIT_SIGNAL, handler=self.lan_recce_exit). \
      catch(signal=signals.ip_addresses_found, handler=self.lan_recce_ip_addresses_found). \
      to_method()

    self.fill_arp_table = self.create(state='fill_arp_table'). \
      catch(signals.ENTRY_SIGNAL, handler=self.fill_arp_table_entry). \
      catch(signals.EXIT_SIGNAL, handler=self.fill_arp_table_exit). \
      catch(signal=signals.arp_time_out, handler=self.fill_arp_table_ARP_TIME_OUT). \
      to_method()

    self.identify_all_ip_addresses = self.create(state='identify_all_ip_addresses'). \
      catch(signals.ENTRY_SIGNAL, handler=self.identify_all_ip_addresses_entry). \
      to_method()

    self.recce_rabbit_consumers = self.create(state='recce_rabbit_consumers'). \
      catch(signals.ENTRY_SIGNAL, handler=self.recce_rabbit_consumers_entry). \
      catch(signals.AMQP_CONSUMER_CHECK, handler=self.recce_rabbit_consumers_AMQP_CONSUMER_CHECK). \
      catch(signals.lan_recce_complete, handler=self.recce_rabbit_consumers_lan_recce_complete). \
      to_method()

    self.nest(self.private_search, parent=None). \
      nest(self.lan_recce, parent=self.private_search). \
      nest(self.fill_arp_table, parent=self.lan_recce). \
      nest(self.identify_all_ip_addresses, parent=self.lan_recce). \
      nest(self.recce_rabbit_consumers, parent=self.lan_recce)

    if live_trace is None:
      live_trace = False
    else:
      live_trace = live_trace

    if live_spy is None:
      live_spy = False
    else:
      live_spy = live_spy

    self.live_trace = live_trace
    self.live_spy = live_spy
    self.start_at(self.private_search)

  @staticmethod
  def private_search_entry(lan, e):
    status = return_status.HANDLED
    lan.subscribe(Event(signals.RECCE_LAN))
    lan.subscribe(Event(signals.AMQP_CONSUMER_CHECK))
    lan.subscribe(Event(signal=signals.LAN_RECCE_COMPLETE))
    lan.my.address = LanRecce.get_working_ip_address()
    return status

  @staticmethod
  def private_search_RECCE_LAN(lan, e):
    status = return_status.HANDLED
    lan.post_fifo(Event(signal=signals.recce_lan))
    return status

  @staticmethod
  def private_recce_lan(lan, e):
    status = lan.trans(lan.lan_recce)
    return status

  @staticmethod
  def private_search_RECCE_COMPLETE(lan, e):
    status = return_status.HANDLED
    pp(e.payload)
    return status

  @staticmethod
  def lan_recce_RECCE_LAN(lan, e):
    status = return_status.HANDLED
    lan.defer(e)
    return status

  @staticmethod
  def lan_recce_init(lan, e):
    status = lan.trans(lan.fill_arp_table)
    return status

  @staticmethod
  def lan_recce_exit(lan, e):
    status = return_status.HANDLED
    lan.recall()
    return status

  @staticmethod
  def lan_recce_ip_addresses_found(lan, e):
    status = lan.trans(lan.recce_rabbit_consumers)
    return status

  @staticmethod
  def fill_arp_table_entry(lan, e):
    status = return_status.HANDLED
    lan.ping_to_fill_arp_table()
    lan.post_fifo(
      Event(signal=signals.arp_time_out),
      times=1,
      period=lan.arp_timeout_sec,
      deferred=True)
    return status

  @staticmethod
  def fill_arp_table_exit(lan, e):
    status = return_status.HANDLED
    lan.cancel_events(Event(signal=signals.arp_time_out))
    return status

  @staticmethod
  def fill_arp_table_ARP_TIME_OUT(lan, e):
    status = lan.trans(lan.identify_all_ip_addresses)
    return status

  @staticmethod
  def identify_all_ip_addresses_entry(lan, e):
    status = return_status.HANDLED
    lan.my.addresses = lan.candidate_ip_addresses()
    lan.other.addresses = list(set(lan.my.addresses) - set(lan.my.address))
    lan.post_fifo(Event(signal=signals.ip_addresses_found))
    return status

  @staticmethod
  def recce_rabbit_consumers_entry(lan, e):
    status = return_status.HANDLED
    lan.candidates = {}
    for ip_address in lan.my.addresses:
      scout = \
        RabbitConsumerScoutChart(ip_address, lan.routing_key, lan.exchange_name)
      lan.candidates[ip_address] = RecceNode(
        searched=False,
        result=False,
        scout=scout
      )
    return status

  @staticmethod
  def recce_rabbit_consumers_lan_recce_complete(lan, e):
    return lan.trans(lan.private_search)

  @staticmethod
  def recce_rabbit_consumers_AMQP_CONSUMER_CHECK(lan, e):
    status = return_status.HANDLED
    ip, result = e.payload.ip_address, e.payload.result
    is_one_of_my_ip_addresses = ip in lan.my.addresses
    is_my_routing_key = e.payload.routing_key is lan.routing_key
    is_my_exchange_name = e.payload.exchange_name is lan.exchange_name

    if is_one_of_my_ip_addresses and is_my_routing_key and is_my_exchange_name:
      lan.candidates[ip] = RecceNode(searched=True, result=result, scout=None)

    search_complete = all([node.searched for node in lan.candidates.values()])

    if search_complete:
      working_ip_addresses = []
      for ip_address, lan_recce_node in lan.candidates.items():
        if lan_recce_node.result:
          working_ip_addresses.append(ip_address)
      payload = RecceCompletePayload(
                  other_addresses=working_ip_addresses,
                  my_address=lan.my.address)
      lan.publish(Event(signal=signals.LAN_RECCE_COMPLETE, payload=payload))
      lan.post_fifo(Event(signal=signals.lan_recce_complete))
    return status

ConnectionDiscoveryPayload = \
  namedtuple('ConnectionDiscoveryPayload', ['hosts', 'amqp_urls', 'dispatcher'])

class MirosRabbitLan(Factory):
  time_out_in_minutes = 30

  def __init__(self, name, routing_key, exchange_name, time_out_in_minutes=None, cache_file_path=None):
    super().__init__(name)
    self.routing_key = routing_key
    self.exchange_name = exchange_name

    self.dict = {}
    self.addresses = None
    self.amqp_urls = None
    self.rabbit_helper = RabbitHelper()

  def change_time_out_in_minutes(self, time_out_in_minutes):
    self.time_out_in_minutes = time_out_in_minutes

  def make_amqp_url(self, ip_address):
    return self.rabbit_helper.make_amqp_url(ip_address)

class MirosRabbitLanChart(MirosRabbitLan):
  def __init__(self,
        routing_key, exchange_name, time_out_in_minutes=None,
        cache_file_path=None, live_trace=None, live_spy=None):

    if time_out_in_minutes is None:
      self.time_out_in_minutes = MirosRabbitLan.time_out_in_minutes
    else:
      self.time_out_in_minutes = time_out_in_minutes

    if cache_file_path:
      self.cache_file_path = cache_file_path
    else:
      self.cache_file_path = None

    super().__init__("lan_chart",
        routing_key,
        exchange_name,
        self.change_time_out_in_minutes,
        self.cache_file_path)

    self.read_or_discover_network_details = self.create(state='read_or_discover_network_details'). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.rodnd_entry). \
      catch(signal=signals.connections_discovered, handler=self.rodnd_connection_discovered). \
      catch(signal=signals.CACHE, handler=self.rodnd_CACHE). \
      to_method()

    self.discover_network = self.create(state='discover_network'). \
      catch(signal=signals.ENTRY_SIGNAL, handler=self.dn_entry). \
      catch(signal=signals.LAN_RECCE_COMPLETE, handler=self.dn_LAN_RECCE_COMPLETE). \
      to_method()

    self.nest(self.read_or_discover_network_details, parent=None). \
        nest(self.discover_network, parent=self.read_or_discover_network_details)

    if live_trace is None:
      live_trace = False
    else:
      live_trace = live_trace

    if live_spy is None:
      live_spy = False
    else:
      live_spy = live_spy

    self.live_trace = live_trace
    self.live_spy = live_spy
    self.start_at(self.read_or_discover_network_details)

  @staticmethod
  def rodnd_entry(chart, e):
    status = return_status.HANDLED
    if not hasattr(chart, 'cache_file_chart'):
      if chart.cache_file_path is None:
        chart.file_path = '.miros_rabbitmq_lan_cache.json'
      chart.file_name = os.path.basename(chart.file_path)
      chart.cache_file_chart = CacheFileChart(
        file_path=chart.file_path,
        live_trace=True)
    if not hasattr(chart, 'rabbitmq_lan_recce_chart'):
      chart.rabbit_lan_reccee_chart = LanRecceChart(chart.routing_key, chart.exchange_name)
    chart.subscribe(Event(signal=signals.LAN_RECCE_COMPLETE))
    chart.subscribe(Event(signal=signals.CACHE))
    chart.publish(Event(signal=signals.CACHE_FILE_READ))
    return status

  @staticmethod
  def rodnd_connection_discovered(chart, e):
    status = return_status.HANDLED
    payload = ConnectionDiscoveryPayload(
      hosts=chart.addresses,
      amqp_urls=chart.amqp_urls,
      dispatcher=chart.name)
    chart.publish(Event(signal=signals.CONNECTION_DISCOVERY, payload=payload))
    return status

  @staticmethod
  def rodnd_CACHE(chart, e):
    status = return_status.HANDLED
    if e.payload.file_name == chart.file_name:
      if e.payload.expired:
        status = chart.trans(chart.discover_network)
      else:
        chart.addresses = e.payload.dict['addresses']
        chart.amqp_urls = e.payload.dict['amqp_urls']
        chart.post_fifo(Event(signal=signals.connections_discovered))
    return status

  @staticmethod
  def dn_entry(chart, e):
    status = return_status.HANDLED
    chart.publish(Event(signal=signals.RECCE_LAN))
    return status

  @staticmethod
  def dn_LAN_RECCE_COMPLETE(chart, e):
    status = return_status.HANDLED
    chart.addresses = e.payload.other_addresses
    chart.amqp_urls = [chart.make_amqp_url(a) for a in chart.addresses]
    chart.post_fifo(Event(signal=signals.connections_discovered))
    chart.dict['addresses'] = chart.addresses
    chart.dict['amqp_urls'] = chart.amqp_urls
    chart.dict['time_out_in_minutes'] = chart.time_out_in_minutes
    payload = CacheWritePayload(json=json.dumps(chart.dict, indent=2, sort_keys=True))
    chart.publish(Event(signal=signals.CACHE_FILE_WRITE, payload=payload))
    return status

class MirosRabbitManualNetwork(Factory):

  def __init__(self, name, routing_key, exchange_name, file_path=None):
    super().__init__(name)
    self.routing_key = routing_key
    self.exchange_name = exchange_name
    self.dict = {}

    self.rabbit_helper = RabbitHelper()
    self.hosts = None
    self.live_hosts = None
    self.live_amqp_urls = None
    self.dead_hosts = None
    self.dead_amqp_urls = None
    self.manual_file_path = None

  def make_amqp_url(self, ip_address):
    return self.rabbit_helper.make_amqp_url(ip_address)


class MirosRabbitManualNetworkChart(MirosRabbitManualNetwork):
  def __init__(self, routing_key, exchange_name, cache_file_path=None, live_trace=None, live_spy=None):
    if cache_file_path:
      self.cache_file_path = cache_file_path
    else:
      self.cache_file_path = None

    super().__init__("manual_chart",
        routing_key,
        exchange_name,
        self.cache_file_path)

    self.read_and_evaluate_network_details = \
      self.create(state='read_and_evaluate_network_details') .\
        catch(signal=signals.ENTRY_SIGNAL, handler=self.raend_entry). \
        catch(signal=signals.network_evaluated, handler=self.raend_network_evaluated). \
        catch(signal=signals.CONNECTION_DISCOVERY, handler=self.raend_CONNECTION_DISCOVERY). \
        catch(signal=signals.CACHE, handler=self.raend_CACHE). \
        to_method()

    self.evaluated_network = \
      self.create(state='evaluated_network'). \
        catch(signal=signals.ENTRY_SIGNAL, handler=self.en_entry). \
        catch(signal=signals.AMQP_CONSUMER_CHECK, handler=self.en_AMQP_CONSUMER_CHECK). \
        to_method()

    self. \
      nest(self.read_and_evaluate_network_details, parent=None). \
      nest(self.evaluated_network, parent=self.read_and_evaluate_network_details)

    if live_trace is None:
      live_trace = False
    else:
      live_trace = live_trace

    if live_spy is None:
      live_spy = False
    else:
      live_spy = live_spy

    self.live_trace = live_trace
    self.live_spy = live_spy

    self.start_at(self.read_and_evaluate_network_details)

  # raend
  @staticmethod
  def raend_entry(chart, e):
    status = return_status.HANDLED
    if not hasattr(chart, 'manual_file_chart'):
      chart.file_path = '.miros_rabbitmq_hosts.json'
      chart.file_name = os.path.basename(chart.file_path)
      chart.manual_file_chart = CacheFileChart(file_path=chart.file_path)
    chart.subscribe(Event(signal=signals.CACHE))
    chart.subscribe(Event(signal=signals.AMQP_CONSUMER_CHECK))
    chart.subscribe(Event(signal=signals.CONNECTION_DISCOVERY))
    chart.publish(Event(signal=signals.CACHE_FILE_READ))
    return status

  @staticmethod
  def raend_network_evaluated(chart, e):
    status = return_status.HANDLED
    payload = ConnectionDiscoveryPayload(
      hosts=chart.live_hosts,
      amqp_urls=chart.live_amqp_urls,
      dispatcher=chart.name)
    chart.publish(Event(signal=signals.CONNECTION_DISCOVERY, payload=payload))
    return status

  @staticmethod
  def raend_CONNECTION_DISCOVERY(chart, e):
    status = return_status.HANDLED
    pp(e.payload)
    return status

  @staticmethod
  def raend_CACHE(chart, e):
    status = return_status.HANDLED
    if e.payload.file_name == chart.file_name:
      chart.hosts = e.payload.dict['hosts']
      chart.live_hosts, chart.live_amqp_urls = [], []
      status = chart.trans(chart.evaluated_network)
    return status

  @staticmethod
  def en_entry(chart, e):
    status = return_status.HANDLED
    chart.candidates = {}
    for host in chart.hosts:
      # This will cause AMQP_CONSUMER_CHECK events to be published
      chart.candidates[host] = \
        RecceNode(
            searched=False,
            result=False,
            scout=RabbitConsumerScoutChart(
              host,
              chart.routing_key,
              chart.exchange_name))
    return status

  @staticmethod
  def en_AMQP_CONSUMER_CHECK(chart, e):
    status = return_status.HANDLED
    h, result = e.payload.ip_address, e.payload.result
    is_one_of_my_hosts = h in chart.hosts
    is_my_routing_key = e.payload.routing_key in chart.routing_key
    is_my_exchange_name = e.payload.exchange_name in chart.exchange_name
    if is_one_of_my_hosts and is_my_routing_key and is_my_exchange_name:
      chart.candidates[h] = RecceNode(searched=True, result=result, scout=None)
      if result:
        chart.live_hosts.append(h)
        chart.live_amqp_urls.append(chart.make_amqp_url(h))
      else:
        chart.dead_hosts.append(h)
        chart.dead_amqp_urls.append(chart.make_amqp_url(h))
    search_completed = all([node.searched for node in chart.candidates.values()])
    if search_completed:
      chart.post_fifo(Event(signal=signals.network_evaluated))
    return status

#chart = MirosRabbitManualNetwork('miros_rabbit_manual_network',
#    routing_key='heya.man',
#    exchange_name='miros.mesh.exchange')
#
#read_and_evaluate_network_details = \
#  chart.create(state='read_and_evaluate_network_details') .\
#    catch(signal=signals.ENTRY_SIGNAL, handler=raend_entry). \
#    catch(signal=signals.network_evaluated, handler=raend_network_evaluated). \
#    catch(signal=signals.CONNECTION_DISCOVERY, handler=raend_CONNECTION_DISCOVERY). \
#    catch(signal=signals.CACHE, handler=raend_CACHE). \
#    to_method()
#
#evaluated_network = \
#  chart.create(state='evaluated_network'). \
#    catch(signal=signals.ENTRY_SIGNAL, handler=en_entry). \
#    catch(signal=signals.AMQP_CONSUMER_CHECK, handler=en_AMQP_CONSUMER_CHECK). \
#    to_method()
#
#chart. \
#  nest(read_and_evaluate_network_details, parent=None). \
#  nest(evaluated_network, parent=read_and_evaluate_network_details)


#chart = MirosRabbitLan(routing_key='heya.man', exchange_name='miros.mesh.exchange')
#
#read_or_discover_network_details = chart.create(state='read_or_discover_network_details'). \
#  catch(signal=signals.ENTRY_SIGNAL, handler=rodnd_entry). \
#  catch(signal=signals.connections_discovered, handler=rodnd_connection_discovered). \
#  catch(signal=signals.CACHE, handler=rodnd_CACHE). \
#  to_method()
#
#discover_network = chart.create(state='discover_network'). \
#  catch(signal=signals.ENTRY_SIGNAL, handler=dn_entry). \
#  catch(signal=signals.LAN_RECCE_COMPLETE, handler=dn_LAN_RECCE_COMPLETE). \
#  to_method()
#
#chart.nest(read_or_discover_network_details, parent=None). \
#  nest(discover_network, parent=read_or_discover_network_details)

if __name__ == '__main__':
  #cache_chart = CacheFileChart(live_trace=True)
  #time.sleep(2)
  #cache_chart.post_fifo(Event(signal=signals.CACHE_FILE_READ))
  #scout1 = RabbitConsumerScoutChart(
  #          '192.168.1.69',
  #          'heya.man',
  #          'miros.mesh.exchange')

  #mrl = MirosRabbitLanChart(routing_key='heya.man',
  #    exchange_name='miros.mesh.exchange', live_trace = True)

  #chart.live_trace = True
  #chart.start_at(read_and_evaluate_network_details)
  MirosRabbitManualNetworkChart(
      'heya_man',
      'miros.mesh.exchange'
      )
  #scout2 = RabbitConsumerScoutChart(
  #          '192.168.1.77',
  #          'heya.man',
  #          'miros.mesh.exchange',
  #          live_trace = True)
  #scout3 = RabbitConsumerScoutChart(
  #          '192.168.1.75',
  #          'heya.man',
  #          'miros.mesh.exchange',
  #          live_trace = True)
  time.sleep(3)
  #lan_recce = LanRecceChart(
  #  routing_key='heya.man',
  #  exchange_name='miros.mesh.exchange',
  #  live_trace=True)
  #lan_recce.post_fifo(Event(signal=signals.RECCE_LAN))

  time.sleep(1)
  time.sleep(50)
  #sm = MirosRabbitMQConnections()
  #sm.append_automatic(address='192.168.1.74')
  #sm.append_manual_live(address='192.168.1.74')
  #sm.append_manual_dead(address='192.168.1.74')
  # sm.remove_all_automatic()
  #print("expired? {}".format(sm.cached_expired()))
  #print("{}".format(sm.created_at()))

  # network memory
  #   entry:
  #    create cache file chart
  #    request read
  #   Cache:
  #    !expired:
  #      update addresses/calculate AMQP urls
  #    experied:
  #      discover_network
  #   discover_network
  #     entry:
  #       create recce object
  #       wait for NETWORK_RESULTS
  #       created dict object
  #       post CACHE_WRITE
  #       broadcast cache
  #     
