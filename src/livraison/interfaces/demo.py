"""Fenêtre de test de Flet. Lancement : flet run src/livraison/interfaces/demo.py
Ajouter --web pour l'ouvrir dans le navigateur."""

import flet as ft


def main(page: ft.Page):
    page.title = "Livraison SMA"
    compteur = ft.Text("0", size=40)

    def incrementer(e):
        compteur.value = str(int(compteur.value) + 1)
        page.update()

    page.add(
        ft.Text("L'interface Flet fonctionne.", size=20),
        compteur,
        ft.Button("Cliquer", on_click=incrementer),
    )


if __name__ == "__main__":
    ft.run(main)
