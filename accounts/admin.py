from django.contrib import admin

from .models import DriverProfile, PassengerProfile, UserProfile


admin.site.register(UserProfile)
admin.site.register(PassengerProfile)
admin.site.register(DriverProfile)