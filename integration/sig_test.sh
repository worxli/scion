#!/bin/bash

# Create scion topo and sig config
./scion.sh topology -c topology/Tiny.topo -d --sig -n 242.0.0.0/16
# Start scion
./scion.sh start
# Start sigs
./tools/dc.sh sig up -d
# Start testing containers
./tools/dc.sh tester up -d

# Run ping
./bin/ping_sig_integration


# Run iperf
# ./bin/sig_iperf_integration

# ./tools/dc.sh sig_tester tester_1-ff00_0_110 bash -c "ping "
# ./tools/dc.sh sig_tester tester_1-ff00_0_111 bash -c "route del default; route add default gw 172.14.0.29 eth0; iperf -c 172.14.0.22"

# Run some other tests
# ...

# Stop everything
# ./tools/dc.sh down
