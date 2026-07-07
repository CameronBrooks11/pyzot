from pyzot.db import ZoteroDatabase
from pyzot.queries.search import search_items, search_by_author

def test_workflow():
    try:
        with ZoteroDatabase() as db:
            bayesian = search_items(db, "bayesian", fields=["title"])
            numair   = search_by_author(db, "Numair")
            
            seen = set()
            for item in bayesian + numair:
                if item.item_id in seen:
                    continue
                seen.add(item.item_id)
                for att in item.attachments:
                    if "pdf" in att.content_type.lower() and att.file_exists:
                        print(f"{item.key}\t{att.absolute_path}")
            print("Workflow test completed successfully.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_workflow()
