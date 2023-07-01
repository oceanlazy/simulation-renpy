init python:
    config.quit_action = Quit(confirm=False)

    config.automatic_images = [' ', '_', '/']
    config.automatic_images_strip = ['images', 'characters']
    config.automatic_images_minimum_components = 1
    config.predict_screen_statements = False
    config.predict_screens = False