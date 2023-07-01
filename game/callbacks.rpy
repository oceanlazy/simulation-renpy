init python:
    def begin_small_talk(plan_data):
        plan_data.first_character.say('callback begin example')

    def finish_small_talk(plan_data):
        plan_data.first_character.say('callback finish example')
