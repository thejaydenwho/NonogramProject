# NonogramProject
To run the nonagram project on vnc.html first run in bash:

# Clean up everything
pkill -9 python; pkill -9 swipl; pkill Xvfb; pkill x11vnc; pkill websockify
rm -f /tmp/.X99-lock

# Start Fake Display
Xvfb :99 -screen 0 1280x800x24 &
sleep 2

# Start VNC Server in the background
export DISPLAY=:99
x11vnc -display :99 -nopw -listen localhost -xkb -bg

# Start the Proxy
~/noVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6080

afterwards run:

export DISPLAY=:99
python3 -u main.py

