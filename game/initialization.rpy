init python:
    import time
    import re
    from datetime import datetime, timedelta
    from kernel.simulation.sim import Simulation
    from kernel import models as simulation_models
    from kernel import settings as simulation_settings
    from kernel import utils as simulation_utils
    from kernel.simulation import plans as simulation_plans
    from kernel.simulation import routes as simulation_routes
    from kernel.simulation.player import PlayerController

    simulation = Simulation()
    player = simulation_models.Character.objects.get(id=simulation_settings.PLAYER_ID)
    player_controller = PlayerController(player, simulation)
    character_interact = None
    generate_menu_options_limit = 5
