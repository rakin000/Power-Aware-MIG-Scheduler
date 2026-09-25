class MonitorAgent:
    def __init__(self, name: str):
        self.name = name

    def discover(self):
        """Discover resources related to the monitor."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    def query_metrics(self):
        """Query metrics specific to the monitor."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    def get_label(self):
        """Return a small string identifying fields related to this agent."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    def update(self, args):
        """Update internal state"""
        raise NotImplementedError("This method should be implemented in subclasses.")