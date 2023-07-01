screen choice_yesno(items):
    style_prefix "choice"

    use quick_menu

    hbox xpos 465 ypos 475 spacing 50:
        for i in items:
            textbutton i.caption action i.action xsize 150
