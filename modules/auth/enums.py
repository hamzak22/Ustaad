from enum import Enum

class UserRoleEnum(Enum) :
    CUSTOMER = "Customer"
    WORKER = "Worker"

class AvailabilityEnum(Enum) :
    AVAILABLE = "Available"
    BUSY = "Busy"
    OFFLINE = "Offline"