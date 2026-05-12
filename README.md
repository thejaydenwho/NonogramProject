# NonogramProject
To run the nonagram project on vnc.html first run in bash:

# clean old processes
pkill Xvfb
pkill x11vnc
pkill websockify

# remove stale lock
rm -f /tmp/.X99-lock

# start fake display
Xvfb :99 -screen 0 1280x800x24 &

# use that display
export DISPLAY=:99

# start VNC server
x11vnc -display :99 -nopw -listen localhost -xkb

second run:

~/noVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6080

open up the vnc html and run:

export DISPLAY=:99
python3 main.py

