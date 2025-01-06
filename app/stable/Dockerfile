
#
# Setup Stage: install apps
#
# This is a dedicated stage so that donwload archives don't end up on 
# production image and consume unnecessary space.
#

FROM ubuntu:22.04 as setup


ENV IB_GATEWAY_VERSION=10.23.2a
ENV IB_GATEWAY_RELEASE_CHANNEL=latest
ENV IBC_VERSION=3.17.0

# Prepare system
RUN apt-get update -y
RUN apt-get install --no-install-recommends --yes \
  curl \
  ca-certificates \
  unzip

WORKDIR /tmp/setup

# Install IB Gateway
# Use this instead of "RUN curl .." to install a local file:
#COPY ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh .
RUN curl -sSL https://github.com/UnusualAlpha/ib-gateway-docker/releases/download/ibgateway-${IB_GATEWAY_RELEASE_CHANNEL}%40${IB_GATEWAY_VERSION}/ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh \
  --output ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh
RUN curl -sSL https://github.com/UnusualAlpha/ib-gateway-docker/releases/download/ibgateway-${IB_GATEWAY_RELEASE_CHANNEL}%40${IB_GATEWAY_VERSION}/ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh.sha256 \
  --output ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh.sha256
RUN sha256sum --check ./ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh.sha256
RUN chmod a+x ./ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh
RUN ./ibgateway-${IB_GATEWAY_VERSION}-standalone-linux-x64.sh -q -dir /root/Jts/ibgateway/${IB_GATEWAY_VERSION}
COPY ./config/ibgateway/jts.ini /root/Jts/jts.ini

# Install IBC
RUN curl -sSL https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IBCLinux-${IBC_VERSION}.zip --output IBCLinux-${IBC_VERSION}.zip
RUN mkdir /root/ibc
RUN unzip ./IBCLinux-${IBC_VERSION}.zip -d /root/ibc
RUN chmod -R u+x /root/ibc/*.sh 
RUN chmod -R u+x /root/ibc/scripts/*.sh
COPY ./config/ibc/config.ini.tmpl /root/ibc/config.ini.tmpl

# Copy scripts
COPY ./scripts /root/scripts

#
# Build Stage: build production image
#

FROM ubuntu:22.04

ENV IB_GATEWAY_VERSION=10.23.2a

WORKDIR /root

# Prepare system
RUN apt-get update -y &&  DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata

RUN apt-get install --no-install-recommends --yes \
  gettext \
  xvfb \
  libxslt-dev \
  libxrender1 \
  libxtst6 \
  libxi6 \
  libgtk2.0-bin \
  socat \
  x11vnc \
  git \
  redis-server \
  wget \
  unzip \
  tmux \
  openssh-client \
  net-tools \
  vim \
  dos2unix

# Copy files
COPY --from=setup /root/ .
RUN chmod a+x /root/scripts/*.sh
COPY --from=setup /usr/local/i4j_jres/ /usr/local/i4j_jres

# IBC env vars
ENV TWS_MAJOR_VRSN ${IB_GATEWAY_VERSION}
ENV TWS_PATH /root/Jts
ENV IBC_PATH /root/ibc
ENV IBC_INI /root/ibc/config.ini
ENV TWOFA_TIMEOUT_ACTION exit

RUN apt-get install -y software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa

# TBOT: Set python3.9 as a default python
RUN apt-get install -y python3.9 python3.9-venv python3.9-dev python3.9-distutils python3-pip && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1

# TBOT: Create a non-root user and set its home directory
RUN useradd -m tbot

# TBOT: Set the working directory to the user's home directory
WORKDIR /home/tbot

# TBOT: copy environment variables
COPY ./tbot/tbot_run.sh /home/tbot/tbot_run.sh
RUN chmod a+x /home/tbot/tbot_run.sh

# TBOT: Set default git repository and allow user to override
ARG TBOT_TRADINGBOAT_GIT_REPO=https://github.com/mporenta/tbot-tradingboat.git
ARG TBOT_TRADINGBOAT_GIT_BRANCH=main

ARG TBOT_TVWB_GIT_REPO=https://github.com/mporenta/tradingview-webhooks-bot.git
ARG TBOT_TVWB_GIT_BRANCH=main

# Add GitHub to known hosts for SSH, copy SSH keys, and clone repository conditionally
COPY ./tbot/* /home/tbot/.ssh/

# Copy the script to detect and copy the SSH key
COPY ./tbot/copy_ssh_key.sh /home/tbot/copy_ssh_key.sh
RUN chmod +x /home/tbot/copy_ssh_key.sh

# TBOT: Set permissions if keys exist
RUN if echo "${TBOT_TRADINGBOAT_GIT_REPO}" | grep -q "git@"; then \
        /home/tbot/copy_ssh_key.sh && \
        chmod 600 /home/tbot/.ssh/id_rsa && \
        ssh-keyscan github.com > /home/tbot/.ssh/known_hosts && \
        git config --global user.email "you@example.com" && \
        git config --global user.name "Your Name" && \
        git config --global core.sshCommand "ssh -i /home/tbot/.ssh/id_rsa -o StrictHostKeyChecking=no"; \
    fi

# TBOT: Install common python libraries for Tradingboat globally
RUN pip install libtmux loguru

# TBOT: create and activate the virtual environment
RUN python3.9 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN . /opt/venv/bin/activate
RUN git clone -b ${TBOT_TRADINGBOAT_GIT_BRANCH} ${TBOT_TRADINGBOAT_GIT_REPO} /home/tbot/develop/github/tbot-tradingboat
WORKDIR /home/tbot/develop/github/tbot-tradingboat
# Install dependencies in the virtual environment
RUN pip install -r requirements.txt
RUN pip install -e .
RUN chmod a+x /home/tbot/develop/github/tbot-tradingboat/tbottmux/*.sh

RUN git clone -b ${TBOT_TVWB_GIT_BRANCH} ${TBOT_TVWB_GIT_REPO} /home/tbot/develop/github/tradingview-webhooks-bot
WORKDIR /home/tbot/develop/github/tradingview-webhooks-bot/src
#COPY ./event.py /home/tbot/develop/github/tradingview-webhooks-bot/src/components/events/base/event.py

#COPY ./commons.py /home/tbot/develop/github/tradingview-webhooks-bot/src/commons.py

# Copy the local version of orders into the container
COPY ./templates/order_base.html /home/tbot/develop/github/tradingview-webhooks-bot/src/templates/order_base.html
#COPY ./order_base.html /home/tbot/develop/github/tradingview-webhooks-bot/src/templates/orders.html
COPY ./flask/main.py /home/tbot/develop/github/tradingview-webhooks-bot/src/main.py
#COPY ./flask/tbot.py /home/tbot/develop/github/tradingview-webhooks-bot/src/tbot.py

#COPY ./tbot_dashboard.html /home/tbot/develop/github/tradingview-webhooks-bot/src/templates/tbot_dashboard.html
#COPY ./service_error.html /home/tbot/develop/github/tradingview-webhooks-bot/src/templates/service_error.html
COPY ./static/img/favicon.ico  /home/tbot/develop/github/tradingview-webhooks-bot/src/static/img/favicon.ico


# Copy the PnL monitoring script into the TBOT_APP_HOME directory
#COPY ./pnl_monitor.py /home/tbot/develop/github/tbot-tradingboat/pnl_monitor.py
ENV TVWB_UNIQUE_KEY=${TVWB_UNIQUE_KEY:-}
ENV WEBHOOK_PNL_THRESHOLD=-300.0

# Install dependencies in the virtual environment
RUN pip install -r requirements.txt
# TBOT: Set the default directory
WORKDIR /home/tbot/develop/github/tbot-tradingboat

COPY ./scripts/fork_ports_delayed.sh /root/scripts/fork_ports_delayed.sh
COPY ./scripts/run_x11_vnc.sh /root/scripts/run_x11_vnc.sh
RUN dos2unix /root/scripts/*.sh && chmod a+x /root/scripts/*.sh

# Start run script
RUN dos2unix /home/tbot/tbot_run.sh && chmod a+x /home/tbot/tbot_run.sh
CMD ["/home/tbot/tbot_run.sh"]