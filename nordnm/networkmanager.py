from nordnm import utils
from nordnm import paths

import subprocess
import shutil
import os
import configparser
import logging
from distutils.version import LooseVersion
import re

logger = logging.getLogger(__name__)


def restart():
    try:
        output = subprocess.run(['systemctl', 'restart', 'NetworkManager'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        logger.info("NetworkManager restarted successfully!")
        return True

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def get_version():
    try:
        output = subprocess.run(['NetworkManager', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        version_string = re.split(",|-", output.stdout.decode())[0].strip()

        return version_string

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def reload_connections():
    try:
        output = subprocess.run(['nmcli', 'connection', 'reload'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        return True

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def get_vpn_connections():
    try:
        output = subprocess.run(['nmcli', '--mode', 'tabular', '--terse', '--fields', 'TYPE,NAME', 'connection', 'show'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        lines = output.stdout.decode('utf-8').split('\n')

        vpn_connections = []
        for line in lines:
            if line:
                elements = line.strip().split(':')

                if (elements[0] == 'vpn'):
                    vpn_connections.append(elements[1])

        return vpn_connections

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False


def get_interfaces(wifi=True, ethernet=True):
    try:
        output = subprocess.run(['nmcli', '--mode', 'tabular', '--terse', '--fields', 'TYPE,DEVICE', 'device', 'status'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        lines = output.stdout.decode('utf-8').split('\n')

        interfaces = []
        for line in lines:
            if line:
                elements = line.strip().split(':')

                if (wifi and elements[0] == 'wifi') or (ethernet and elements[0] == 'ethernet'):
                    interfaces.append(elements[1])

        return interfaces

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def set_global_mac_address(value):
    MIN_VERSION = "1.4.0"
    nm_version = get_version()

    if nm_version:
        if LooseVersion(nm_version) >= LooseVersion(MIN_VERSION):
            mac_config = configparser.ConfigParser(interpolation=None)

            mac_config['connection-mac-randomization'] = {}
            mac_config['connection-mac-randomization']['wifi.cloned-mac-address'] = value
            mac_config['connection-mac-randomization']['ethernet.cloned-mac-address'] = value

            try:
                with open(paths.MAC_CONFIG, 'w') as config_file:
                    mac_config.write(config_file)

                logger.info("Global NetworkManager MAC address settings set to '%s'.", value)
                return True
            except Exception:
                logger.error("Could not save MAC address configuration to '%s'", paths.MAC_CONFIG)
                return False
        else:
            logger.error("NetworkManager v%s or greater is required to change MAC address settings. You have v%s.", MIN_VERSION, nm_version)
            return False
    else:
        logger.error("Could not get the version of NetworkManager in use. Aborting.")
        return False


def remove_global_mac_address():
    try:
        os.remove(paths.MAC_CONFIG)
        logger.info("Global NetworkManager MAC address settings have been removed successfully.")
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error("Could not remove the MAC address settings file '%s': %s" % (paths.MAC_CONFIG, e))
        return False


def remove_killswitch(log=True):
    try:
        os.remove(paths.KILLSWITCH_DATA)
    except FileNotFoundError:
        pass

    try:
        os.remove(paths.KILLSWITCH_SCRIPT)

        if log:
            logger.info("Network kill-switch disabled.")

        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error("Error attempting to remove kill-switch: %s" % e)
        return False


def set_killswitch(log=True):
    killswitch_script = (
        '#!/bin/bash\n'
        'PERSISTENCE_FILE=' + paths.KILLSWITCH_DATA + '\n\n'
        'case $2 in'
        '  vpn-up)\n'
        '    nmcli -f type,device connection | awk \'$1~/^vpn$/ && $2~/[^\-][^\-]/ { print $2; }\' > "${PERSISTENCE_FILE}"\n'
        '  ;;\n'
        '  vpn-down)\n'
        '    xargs -n 1 -a "${PERSISTENCE_FILE}" nmcli device disconnect\n'
        '  ;;\n'
        'esac\n'
        )

    try:
        with open(paths.KILLSWITCH_SCRIPT, "w") as killswitch:
            print(killswitch_script, file=killswitch)

        utils.make_executable(paths.KILLSWITCH_SCRIPT)

        if log:
            logger.info("Network kill-switch enabled.")

        return True
    except Exception as e:
        logger.error("Error attempting to set kill-switch: %s" % e)
        return False


def set_auto_connect(connection_name):
    interfaces = get_interfaces()

    if interfaces:
        interface_string = '|'.join(interfaces)

        auto_script = (
            '#!/bin/bash\n\n'
            'if [[ "$1" =~ ' + interface_string + ' ]] && [[ "$2" =~ up|connectivity-change ]]; then\n'
            '  nmcli con up id "' + connection_name + '"\n'
            'fi\n'
            )

        try:
            with open(paths.AUTO_CONNECT_SCRIPT, "w") as auto_connect:
                print(auto_script, file=auto_connect)

            utils.make_executable(paths.AUTO_CONNECT_SCRIPT)
            return True
        except Exception as e:
            logger.error("Error attempting to set auto-conect: %s" % e)
            return False
    else:
        logger.error("No interfaces found to use with auto-connect")
        return False


def remove_autoconnect():
    try:
        os.remove(paths.AUTO_CONNECT_SCRIPT)
        logger.info("Auto-connect disabled.")
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error("Error attempting to remove auto-connect: %s" % e)
        return False


def import_connection(file_path, connection_name, username=None, password=None, dns_list=None, ipv6=False):
    # Create a temporary config with the connection name, so we can import the config with its prettified name
    temp_path = os.path.join(os.path.dirname(file_path), connection_name + '.ovpn')
    shutil.copy(file_path, temp_path)

    output = subprocess.run(['nmcli', 'connection', 'import', 'type', 'openvpn', 'file', temp_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.remove(temp_path) # Remove the temporary renamed config we created
    output.check_returncode()

    # Populate all connection options into connection_options
    connection_options = {
        '+vpn.secrets': ['password='+password],
        '+vpn.data': ['username='+username, 'password-flags=0'],
        '+connection.permissions': ['user:'+utils.get_current_user()],
    }

    if not ipv6:
        connection_options['ipv6.method'] = ['ignore']

    if dns_list:
        dns_string = ';'.join(map(str, dns_list))
        connection_options['+ipv4.dns'] = [dns_string]
        connection_options['+ipv4.ignore-auto-dns'] = ['true']

    try:
        for location, values in connection_options.items():
            for value in values:
                output = subprocess.run(['nmcli', 'connection', 'modify', connection_name, location, value], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output.check_returncode()

        return True

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def enable_connection(connection_name):
    try:
        output = subprocess.run(['nmcli', 'connection', 'up', connection_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        return True

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def disable_connection(connection_name):
        try:
            output = subprocess.run(['nmcli', 'connection', 'down', connection_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output.check_returncode()

            return True

        except subprocess.CalledProcessError:
            error = utils.format_std_string(output.stderr)
            logger.error(error)
            return False

        except Exception as ex:
            logger.error(ex)
            return False


def remove_connection(connection_name):
    try:
        output = subprocess.run(['nmcli', 'connection', 'delete', connection_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()

        return True

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def get_active_vpns(active_servers):
    active_vpns = set([])

    try:
        output = subprocess.run(['nmcli', '--mode', 'tabular', '--terse', '--fields', 'TYPE,NAME,UUID', 'connection', 'show', '--active'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output.check_returncode()
        lines = output.stdout.decode('utf-8').split('\n')

        for line in lines:
            if line:
                elements = line.strip().split(':')

                if elements[0] == "vpn":  # Only count VPNs managed by this tool.
                    for server in active_servers.values():
                        if elements[1] == server['name'] and elements[2] not in active_vpns:
                            active_vpns.add(elements[2])  # Add the UUID to our set

        return active_vpns

    except subprocess.CalledProcessError:
        error = utils.format_std_string(output.stderr)
        logger.error(error)
        return False

    except Exception as ex:
        logger.error(ex)
        return False


def disconnect_active_vpn(active_servers):
    active_vpns = get_active_vpns(active_servers)
    disconnected_vpns = set([])

    for uuid in active_vpns:
        if disable_connection(uuid):
            disconnected_vpns.add(uuid)  # Add the UUID to our set

    return bool(disconnected_vpns)
