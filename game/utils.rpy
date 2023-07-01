init python:
    class SayScreenHide(object):
        def __init__(self, screens=None):
            self.screens = screens or []

        def __enter__(self):
            for screen in self.screens:
                renpy.hide_screen(screen)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            for screen in self.screens:
                renpy.show_screen(screen)

    def generate_menu(objects, attr_name=None, page=0):
        if attr_name:
            choices = [(obj, None) if isinstance(obj, str) else (getattr(obj, attr_name), obj) for obj in objects]
        else:
            choices = objects
        objects_num = len(objects)
        if objects_num > generate_menu_options_limit:
            min_inx = page * generate_menu_options_limit
            choices = choices[min_inx:min_inx+generate_menu_options_limit]
            choices.append(('Next page', 'next'))
        choices.append(('Cancel', 'cancel'))
        choice = renpy.display_menu(choices)
        if choice == 'next':
            page = 0 if page * generate_menu_options_limit >= len(objects) - generate_menu_options_limit else page+1
            return generate_menu(objects, attr_name, page)
        return choice
