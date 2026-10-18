# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

logger = logging.getLogger("fleetpilot.plugins")

addon_meta = {
    "name": "example_plugin",
    "html": '''
    {# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
       SPDX-License-Identifier: GPL-3.0-or-later -#}
    {% extends 'disks/base.html' %}
    {% block title %}Example Plugin – {{ device }}{% endblock %}
    {% block content %}
      <div class="container mt-4">
        <h1>Example Plugin</h1>
        <p>This is an example view for device <strong>{{ device }}</strong>.</p>
        <a href="{{ url_for('disks_index') }}" class="btn btn-secondary">Back to Overview</a>
      </div>
    {% endblock %}
    '''
}

def register(app, core):
    logger.info("[example_plugin] successfully registered.")
