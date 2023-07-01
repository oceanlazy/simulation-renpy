label main_menu:
    $ Start()

label start:
    scene expression 'gui/background.jpg'
    jump choose_action

label choose_action:
    $ player_controller.choose_action_init()



    python:
        text_display = (
            'Time: {}\n'.format(simulation.time.dt.strftime('%H:%M:%S')) +
            'Place: {}\n'.format(player.place.name) +
            'Characters: {}'.format(', '.join(player.place.character_set.filter().values_list('first_name')))
        )
        if simulation_utils.player_data['suitable_places']:
            text_display += '\nTarget place: {}'.format(simulation_utils.player_data['suitable_places'][0].name)

    menu:
        "Interact" if not simulation_utils.player_data['suitable_places'] and not simulation_utils.player_data['is_plans_not_found']:
            $ player_controller.choose_plan()
            jump choose_action
        "Move":
            $ player_controller.move_to_choose()
            jump choose_action
        "Wait" if not simulation_utils.player_data['suitable_places']:
            $ player_controller.wait()
            jump choose_action
        "Continue action" if player.place in simulation_utils.player_data['suitable_places']:
            $ player_controller.next_stage()
            jump choose_action
        "Cancel action" if simulation_utils.player_data['suitable_places']:
            $ player_controller.cancel_plan()
            jump choose_action
        '[text_display]'

label place_characters_choose:
    $ choice = generate_menu(player.place.character_set.filter(id__ne=player.id), 'full_name')
    if choice == 'cancel':
        jump choose_action
    elif choice == 'next':
        jump place_characters_choose
    else:
        $ character_interact = choice
        jump character_interaction


label character_interaction:
    hide screen place_screen
    show screen em
    show screen character_interact_screen
    menu:
        "TEST":
            hide screen em
            hide screen character_interact_screen
            show expression ' '.join([character_interact.title, 'full'])
            $ character_interact.say('Hello! My name is [character_interact.first_name] and yours?')
            hide expression ' '.join([character_interact.title, 'full'])
            show screen em
            jump character_interaction
        "Cancel":
            hide screen character_interact_screen
            show screen place_screen
            $ character_interact = None
            jump choose_action

label game_over():
    hide screen em
    hide screen place_screen
    hide screen character_interact_screen
    "Game over."
    return
