from service import ReportService


def publish_report(record):
    return ReportService().publish(record)
