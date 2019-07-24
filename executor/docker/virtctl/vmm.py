'''
Copyright (2019, ) Institute of Software, Chinese Academy of 

@author: wuheng@otcaix.iscas.ac.cn
@author: wuyuewen@otcaix.iscas.ac.cn
'''

from kubernetes import config, client
from kubernetes.client import V1DeleteOptions
from json import loads
import sys
import shutil
import os
import json
import subprocess

from utils.libvirt_util import vm_state
from utils.utils import addPowerStatusMessage


import logging
import logging.handlers
from utils.utils import ExecuteException

LOG = '/var/log/virtctl.log'

def set_logger(header,fn):
    logger = logging.getLogger(header)

    handler1 = logging.StreamHandler()
    handler2 = logging.handlers.RotatingFileHandler(filename=fn, maxBytes=10000000, backupCount=10)

    logger.setLevel(logging.DEBUG)
    handler1.setLevel(logging.DEBUG)
    handler2.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s %(name)s %(lineno)s %(levelname)s %(message)s")
    handler1.setFormatter(formatter)
    handler2.setFormatter(formatter)

    logger.addHandler(handler1)
    logger.addHandler(handler2)
    return logger

config.load_kube_config(config_file="/root/.kube/config")

GROUP='v1alpha3'
VERSION='cloudplus.io'
VM_PLURAL='virtualmachines'
VMI_PLURAL='virtualmachineimages'

logger = set_logger(os.path.basename(__file__), '/var/log/virtctl.log')

def convert_to_Image(name):
    '''
        execute the vm to image operation.
    '''
    cmd = os.path.split(os.path.realpath(__file__))[0] +'/scripts/mybackup.sh ' + name
    runCmdWithCallback(cmd, toImage, name)

def toImage(name):
    jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachines', name=name)
    jsonDict = jsonStr.copy()
    jsonDict['kind'] = 'VirtualMachineImage'
    jsonDict['metadata']['kind'] = 'VirtualMachineImage'
    del jsonDict['metadata']['resourceVersion']
    del jsonDict['spec']['lifecycle']
    client.CustomObjectsApi().create_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachineimages', body=jsonDict)
    client.CustomObjectsApi().delete_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachines', name=name, body=V1DeleteOptions())
    logger.debug('convert VM to Image successful.')
    
def toVM(name):
    jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachineimages', name=name)
    jsonDict = jsonStr.copy()
    jsonDict['kind'] = 'VirtualMachine'
    jsonDict['metadata']['kind'] = 'VirtualMachine'
    del jsonDict['spec']['lifecycle']
    del jsonDict['metadata']['resourceVersion']
    client.CustomObjectsApi().create_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachines', body=jsonDict)
    client.CustomObjectsApi().delete_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachineimages', name=name, body=V1DeleteOptions())
    logger.debug('convert Image to VM successful.')


def updateOS(name, source, target):
    jsonDict = client.CustomObjectsApi().get_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachines', name=name)
    jsonString = json.dumps(jsonDict)
    if jsonString.find(source) >= 0 and os.path.exists(target):
        shutil.copyfile(target, source)
    else:
        raise Exception('Wrong source or target.')
    jsonDict = deleteLifecycleInJson(jsonDict)
    vm_power_state = vm_state(name).get(name)
    body = addPowerStatusMessage(jsonDict, vm_power_state, 'The VM is %s' % vm_power_state)
    client.CustomObjectsApi().replace_namespaced_custom_object(
        group='cloudplus.io', version='v1alpha3', namespace='default', plural='virtualmachines', name=name, body=body)
    
def deleteLifecycleInJson(jsondict):
    if jsondict:
        '''
        Get target VM name from Json.
        '''
        spec = jsondict['spec']
        if spec:
            lifecycle = spec.get('lifecycle')
            if lifecycle:
                del spec['lifecycle']
    return jsondict

def cmd():
    help_msg = 'Usage: python %s <to-image|to-vm|update-os|--help>' % sys.argv[0]
    if len(sys.argv) < 2 or sys.argv[1] == '--help':
        print (help_msg)
        sys.exit(1)
    
    if len(sys.argv)%2 != 0:
        print ("wrong parameter number")
        sys.exit(1) 
 
    params = {}
    for i in range (2, len(sys.argv) - 1):
        params[sys.argv[i]] = sys.argv[i+1]
        i = i+2
    
    if sys.argv[1] == 'to-image':
        toImage(params['--name'])
    elif sys.argv[1] == 'to-vm':
        toVM(params['--name'])
    elif sys.argv[1] == 'update-os':
        updateOS(params['--domain'], params['--source'], params['--target'])
    else:
        print ('invalid argument!')
        print (help_msg)


'''
Run back-end command in subprocess.
'''
def runCmdWithCallback(cmd, callback, *args):
    std_err = None
    if not cmd:
        #         logger.debug('No CMD to execute.')
        return
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        std_out = p.stdout.readlines()
        std_err = p.stderr.readlines()
        if std_out:
            msg = ''
            isError = False
            for index, line in enumerate(std_out):
                if not str.strip(line):
                    continue
                if str.find('error') > 0:
                    isError = True
                if index == len(std_out) - 1:
                    msg = msg + str.strip(line) + '. '
                else:
                    msg = msg + str.strip(line) + ', '
            if not isError and callback != None:
                callback(args)  #TODO
            logger.debug(str.strip(msg))
        if std_err:
            msg = ''
            for index, line in enumerate(std_err):
                if not str.strip(line):
                    continue
                if index == len(std_err) - 1:
                    msg = msg + str.strip(line) + '. ' + '***More details in %s***' % LOG
                else:
                    msg = msg + str.strip(line) + ', '
            logger.error(str.strip(msg))
            raise ExecuteException('VirtctlError', str.strip(msg))
        #         return (str.strip(std_out[0]) if std_out else '', str.strip(std_err[0]) if std_err else '')
        return
    finally:
        p.stdout.close()
        p.stderr.close()

if __name__ == '__main__':
    cmd()
    pass