from django.apps import AppConfig


class AuctionListConfig(AppConfig):
    name = "auction_list"

    def ready(self):
        import auction_list.signals
