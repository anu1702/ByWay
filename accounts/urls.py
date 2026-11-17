from django.urls import path

from accounts import views

urlpatterns = [
    path("", views.login, name="login"),
    path("register/", views.register, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("home/", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
]
