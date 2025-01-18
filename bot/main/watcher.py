import os
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class EventHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        print(event)
        # wsgi = Path(__file__).parent.parent.parent.joinpath('outline_v2').joinpath('wsgi.py').resolve()
        # os.system(f'touch {wsgi}')
        os.system(f'apachectl -k graceful')


if __name__ == '__main__':
    while True:
        event_handler = EventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=f"{Path(__file__).resolve().parent.parent.joinpath('admin.py')}",
                          recursive=True)
        # observer.schedule(event_handler, path=f"{Path(__file__).resolve().parent.parent.joinpath('models.py')}",
        #                   recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except:
            # observer.stop()
            observer.join()
        time.sleep(1)
