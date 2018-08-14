#!/usr/bin/python3
# Copyright 2018 ETH Zurich
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Stdlib
import copy
import os
from string import Template

# External packages
import yaml

# SCION
from lib.packet.scion_addr import ISD_AS
from lib.util import (
    read_file,
    write_file,
)
from topology.common import _prom_addr_br, _prom_addr_infra

DEFAULT_DOCKER_NETWORK = "172.18.0.0/24"

DOCKER_BASE_CONF = 'base-dc.yml'
DOCKER_SCION_CONF = 'scion-dc.yml'
DOCKER_UTIL_CONF = 'utils-dc.yml'
DOCKER_TESTER_CONF = 'testers-dc.yml'
DOCKER_SIG_CONF = 'sig-dc.yml'
DOCKER_NETWORK_CONF = 'dc-networks.conf'


class DockerGenerator(object):
    def __init__(self, out_dir, topo_dicts, networks, sig):
        self.out_dir = out_dir
        self.topo_dicts = topo_dicts
        self.networks = networks
        self.dc_base_conf = {'version': '3', 'networks': {}, 'volumes': {}}
        self.dc_conf = {'version': '3', 'services': {}}
        self.sig_conf = {'version': '3', 'services': {}}
        self.elem_networks = {}
        self.sig = sig
        self.bridges = {}

    def generate(self):
        self._base_conf()
        self._zookeeper_conf()
        if self.sig:
            self._create_networks()
        for topo_id, topo in self.topo_dicts.items():
            base = topo_id.base_dir(self.out_dir)
            self._br_conf(topo, base)
            self._cs_conf(topo_id, topo, base)
            self._bs_conf(topo_id, topo, base)
            self._ps_conf(topo_id, topo, base)
            self._sciond_conf(topo_id, base)
            self._dispatcher_conf(topo_id, base)
            if self.sig:
                self._create_volumes(topo_id)
                self._sig_conf(topo_id, topo, base)
        self._write_files()

        utils_gen = UtilsGenerator(self.out_dir, self.topo_dicts, self.sig,
                                   self.dc_base_conf['volumes'], self.elem_networks, self.bridges)
        utils_gen.generate()

    def _write_files(self):
        write_file(os.path.join(self.out_dir, DOCKER_SCION_CONF),
                   yaml.dump(self.dc_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_BASE_CONF),
                   yaml.dump(self.dc_base_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_SIG_CONF),
                   yaml.dump(self.sig_conf, default_flow_style=False))

        # Write bridge config file
        text = ''
        for br in self.bridges:
            text += br + ' ' + self.bridges[br] + '\n'
        conf_path = os.path.join(self.out_dir, DOCKER_NETWORK_CONF)
        write_file(conf_path, text)

    def _base_conf(self):
        default_net = {'ipam': {'config': [{'subnet': DEFAULT_DOCKER_NETWORK}]}}
        self.dc_base_conf['networks']['default'] = default_net

    def _create_networks(self):
        for network in self.networks:
            for elem in self.networks[network]:
                if elem not in self.elem_networks:
                    self.elem_networks[elem] = []
                self.elem_networks[elem].append(
                    {'net': str(network), 'ipv4': self.networks[network][elem].ip})
            # Create docker networks/bridges
            net_name = "scn_%03d" % len(self.bridges)
            self.bridges[str(network)] = net_name
            self.dc_base_conf['networks'][net_name] = {'external': True}

    def _create_volumes(self, topo_id):
        self.dc_base_conf['volumes']['vol_disp_%s' % topo_id.file_fmt()] = None
        self.dc_base_conf['volumes']['vol_sciond_%s' % topo_id.file_fmt()] = None

    def _br_conf(self, topo, base):
        raw_entry = {
            'image': 'scion_border',
            'restart': 'always',
            'network_mode': 'host',
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                '${PWD}/logs:/share/logs:rw'
            ],
            'networks': {},
            'command': []
        }
        for k, v in topo.get("BorderRouters", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            entry['volumes'].append('${PWD}/%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('-id=%s' % k)
            entry['command'].append('-prom=%s' % _prom_addr_br(v))
            if self.sig:
                entry.pop('network_mode', None)
                for net in self.elem_networks[k]:
                    ip = str(net['ipv4'])
                    entry['networks'][self.bridges[net['net']]] = {'ipv4_address': ip}
            else:
                entry.pop('networks', None)
            self.dc_conf['services'][k] = entry

    def _sig_conf(self, topo_id, topo, base):
        name = 'sig_%s' % topo_id.file_fmt()
        net = self.elem_networks[topo_id.file_fmt()][0]
        entry = {
            'image': 'scion_sig_testing:latest',
            'container_name': name,
            'restart': 'always',
            'cap_add': [
                'NET_ADMIN',
            ],
            'privileged': True,
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '/dev/net/tun:/dev/net/tun',
                '${PWD}/%s/sig:/share/conf' % base,
                '${PWD}/logs:/share/logs:rw',
            ],
            'networks': {},
            'command': [
                remote_nets(self.elem_networks, topo_id),
                '-id=%s' % name,
                '-ia=%s' % ISD_AS(topo_id.file_fmt()),
                '-ip=%s' % str(net['ipv4']),
                '-config=conf/cfg.json',
            ]
        }
        entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4']+3)}
        self.sig_conf['services'][name] = entry

    def _cs_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_cert',
            'restart': 'always',
            'depends_on': [
                self._sciond_name(topo_id),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '${PWD}/gen-cache:/share/cache:rw',
                '${PWD}/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache'
            ]
        }
        for k, v in topo.get("CertificateService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            if self.sig:
                entry['depends_on'].append('disp_' + topo_id.file_fmt())
            else:
                entry['depends_on'].append('dispatcher')
            entry['volumes'].append('${PWD}/%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('--prom=%s' % _prom_addr_infra(v))
            entry['command'].append(k)
            entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _bs_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_beacon',
            'restart': 'always',
            'depends_on': [
                self._sciond_name(topo_id),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '${PWD}/gen-cache:/share/cache:rw',
                '${PWD}/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache'
            ]
        }
        for k, v in topo.get("BeaconService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            if self.sig:
                entry['depends_on'].append('disp_' + topo_id.file_fmt())
            else:
                entry['depends_on'].append('dispatcher')
            entry['volumes'].append('${PWD}/%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('--prom=%s' % _prom_addr_infra(v))
            entry['command'].append(k)
            entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _ps_conf(self, topo_id, topo, base):
        raw_entry = {
            'image': 'scion_path',
            'restart': 'always',
            'depends_on': [
                self._sciond_name(topo_id),
                'zookeeper'
            ],
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '${PWD}/gen-cache:/share/cache:rw',
                '${PWD}/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache'
            ]
        }
        for k, v in topo.get("PathService", {}).items():
            entry = copy.deepcopy(raw_entry)
            entry['container_name'] = k
            if self.sig:
                entry['depends_on'].append('disp_' + topo_id.file_fmt())
            else:
                entry['depends_on'].append('dispatcher')
            entry['volumes'].append('${PWD}/%s:/share/conf:ro' % os.path.join(base, k))
            entry['command'].append('--prom=%s' % _prom_addr_infra(v))
            entry['command'].append(k)
            entry['command'].append('conf')
            self.dc_conf['services'][k] = entry

    def _zookeeper_conf(self):
        entry = {
            'image': 'zookeeper:latest',
            'container_name': 'zookeeper',
            'restart': 'always',
            'environment': {
                'ZOO_USER': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                '${PWD}/docker/zoo-container.cfg:/conf/zoo.cfg:ro',
                '/var/lib/docker-zk:/var/lib/zookeeper:rw',
                '/run/shm/docker-zk:/dev/shm/zookeeper:rw'
            ],
            'ports': [
                '2181:2181'
            ]
        }
        self.dc_conf['services']['zookeeper'] = entry

    def _sciond_conf(self, topo_id, base):
        name = self._sciond_name(topo_id)
        entry = {
            'image': 'scion_sciond',
            'restart': 'always',
            'container_name': name,
            'depends_on': [],
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '${PWD}/%s:/share/conf:ro' % os.path.join(base, 'endhost'),
                '${PWD}/gen-cache:/share/cache:rw',
                '${PWD}/logs:/share/logs:rw'
            ],
            'command': [
                '--spki_cache_dir=cache',
                name,
                'conf'
            ]
        }
        if self.sig:
            entry['depends_on'].append('disp_' + topo_id.file_fmt())
        else:
            entry['depends_on'].append('dispatcher')
        self.dc_conf['services'][name] = entry

    def _dispatcher_conf(self, topo_id, base):
        entry = {
            'image': 'scion_dispatcher',
            'container_name': 'dispatcher',
            'restart': 'always',
            'environment': {
                'SU_EXEC_USERSPEC': '$LOGNAME',
            },
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro',
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                '${PWD}/logs:/share/logs:rw'
            ],
            'networks': {},
        }

        if self.sig:
            self._multi_dispatcher_conf(topo_id, base, entry)
            return

        # Create dispatcher config
        cfg = "%s/dispatcher/dispatcher.zlog.conf" % base
        tmpl = Template(read_file("topology/zlog.tmpl"))
        write_file(cfg, tmpl.substitute(name="dispatcher", elem="dispatcher"))
        entry['volumes'].append('${PWD}/gen/dispatcher:/share/conf:rw')
        entry['network_mode'] = 'host'
        entry.pop('networks', None)
        self.dc_conf['services']['dispatcher'] = entry

    def _multi_dispatcher_conf(self, topo_id, base, raw_entry):
        tmpl = Template(read_file("topology/zlog.tmpl"))
        entry = copy.deepcopy(raw_entry)
        name = 'disp_%s' % topo_id.file_fmt()
        entry['container_name'] = name
        for net in self.elem_networks[topo_id.file_fmt()]:
            entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4'])}
            volume = '${PWD}/%s/dispatcher:/share/conf:rw' % base
            entry['volumes'].append(volume)
            self.dc_conf['services'][name] = entry
            cfg = "%s/dispatcher/dispatcher.zlog.conf" % base
            write_file(cfg, tmpl.substitute(name="dispatcher", elem=name))

    def _sciond_name(self, topo_id):
        return 'sd' + topo_id.file_fmt()


class UtilsGenerator(object):
    def __init__(self, out_dir, topo_dicts, sig, volumes, elem_networks, bridges):
        self.out_dir = out_dir
        self.topo_dicts = topo_dicts
        self.dc_util_conf = {'version': '3', 'services': {}}
        self.dc_tester_conf = {'version': '3', 'services': {}}
        self.elem_networks = elem_networks
        self.sig = sig
        self.volumes = volumes
        self.bridges = bridges

    def generate(self):
        if not self.sig:
            self._test_conf()
        for topo_id in self.topo_dicts:
            self._create_util_containers()
            if self.sig:
                self._sig_test_conf(topo_id)
        self._write_files()

        text = ''
        for topo_id in self.topo_dicts:
            ip = self.elem_networks[topo_id.file_fmt()][0]['ipv4']+4
            text += str(topo_id) + ' ' + str(ip) + '\n'
            conf_path = os.path.join(self.out_dir, 'sig-test.conf')
            write_file(conf_path, text)

    def _write_files(self):
        write_file(os.path.join(self.out_dir, DOCKER_UTIL_CONF),
                   yaml.dump(self.dc_util_conf, default_flow_style=False))
        write_file(os.path.join(self.out_dir, DOCKER_TESTER_CONF),
                   yaml.dump(self.dc_tester_conf, default_flow_style=False))

    def _create_util_containers(self):
        entry_chown = {
            'image': 'busybox',
            'volumes': [
                '/etc/passwd:/etc/passwd:ro',
                '/etc/group:/etc/group:ro'
            ],
            'command': 'chown -R "$LOGNAME:" /run/shm/volumes/.'
        }
        entry_clean = {
            'image': 'busybox',
            'volumes': [],
            'command': 'sh -c "find /run/shm/volumes -type s -print0 | xargs -r0 rm -v"'
        }
        for volume in self.volumes:
            entry_chown['volumes'].append('%s:/run/shm/volumes/%s' % (volume, volume))
            entry_clean['volumes'].append('%s:/run/shm/volumes/%s' % (volume, volume))
        self.dc_util_conf['services']['chowner'] = entry_chown
        self.dc_util_conf['services']['cleaner'] = entry_clean

    def _test_conf(self):
        entry = {
            'image': 'scion_app_builder',
            'volumes': [
                '/run/shm/dispatcher:/run/shm/dispatcher:rw',
                '/run/shm/sciond:/run/shm/sciond:rw',
                '${PWD}/logs:/home/scion/go/src/github.com/scionproto/scion/logs:rw'
            ],
            'entrypoint': [],
            'command': [
                'tail',
                '-f',
                '/dev/null'
            ]
        }
        entry['container_name'] = 'tester'
        self.dc_tester_conf['services']['tester'] = entry

    def _sig_test_conf(self, topo_id):
        net = self.elem_networks[topo_id.file_fmt()][0]
        entry = {
            # 'image': 'scion_app_builder',
            'image': 'iperf',
            'privileged': True,
            'volumes': [
                'vol_disp_%s:/run/shm/dispatcher:rw' % topo_id.file_fmt(),
                'vol_sciond_%s:/run/shm/sciond:rw' % topo_id.file_fmt(),
                '${PWD}/logs:/home/scion/go/src/github.com/scionproto/scion/logs:rw'
            ],
            'networks': {},
            'entrypoint': [
                './tester.sh',
                str(net['ipv4']+3),
                remote_nets(self.elem_networks, topo_id)
            ],
        }
        name = 'tester_%s' % topo_id.file_fmt()
        entry['container_name'] = name
        entry['networks'][self.bridges[net['net']]] = {'ipv4_address': str(net['ipv4']+4)}
        self.dc_tester_conf['services'][name] = entry


def remote_nets(networks, topo_id):
    rem_nets = []
    for key in networks:
        if 'br' not in key and key != topo_id.file_fmt():
            rem_nets.append(str(networks[key][0]['net']))
    return ','.join(rem_nets)
