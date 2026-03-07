"""Seed trade_categories with all trade types per family.

Revision ID: 0019
Revises: 0018
Create Date: 2025-01-15

Requirements: 3.1, 3.2, 3.5
"""

from __future__ import annotations

import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str = "0018"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Seed data: trade categories grouped by family slug
# ---------------------------------------------------------------------------

TRADE_CATEGORIES = [
    # --- Automotive & Transport ---
    {
        "slug": "general-automotive",
        "display_name": "General Automotive",
        "family_slug": "automotive-transport",
        "icon": "car",
        "description": "General vehicle servicing, repairs, and maintenance workshops.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "inventory", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Vehicle", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Full Service", "description": "Complete vehicle service", "default_price": 250.00, "unit_of_measure": "each"},
            {"name": "WOF Inspection", "description": "Warrant of Fitness inspection", "default_price": 60.00, "unit_of_measure": "each"},
            {"name": "Brake Pad Replacement", "description": "Replace front or rear brake pads", "default_price": 180.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Engine Oil 5W-30 (5L)", "default_price": 45.00, "unit_of_measure": "each"},
            {"name": "Oil Filter", "default_price": 15.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "panel-beating",
        "display_name": "Panel Beating & Spray Painting",
        "family_slug": "automotive-transport",
        "icon": "paintbrush",
        "description": "Collision repair, panel beating, and automotive spray painting.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "inventory", "notifications"],
        "terminology_overrides": {"asset_label": "Vehicle", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Panel Repair", "description": "Dent removal and panel repair", "default_price": 350.00, "unit_of_measure": "each"},
            {"name": "Full Respray", "description": "Complete vehicle respray", "default_price": 3500.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Automotive Paint (1L)", "default_price": 85.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "auto-electrical",
        "display_name": "Auto Electrical",
        "family_slug": "automotive-transport",
        "icon": "zap",
        "description": "Vehicle electrical systems, diagnostics, and wiring.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "inventory", "notifications"],
        "terminology_overrides": {"asset_label": "Vehicle", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Electrical Diagnostic", "description": "Full electrical system diagnostic", "default_price": 120.00, "unit_of_measure": "each"},
            {"name": "Alternator Replacement", "description": "Remove and replace alternator", "default_price": 350.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Car Battery", "default_price": 180.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "tyre-fitting",
        "display_name": "Tyre Fitting & Wheel Alignment",
        "family_slug": "automotive-transport",
        "icon": "circle",
        "description": "Tyre sales, fitting, balancing, and wheel alignment services.",
        "recommended_modules": ["invoicing", "customers", "inventory", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Vehicle", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Tyre Fitting", "description": "Fit and balance single tyre", "default_price": 25.00, "unit_of_measure": "each"},
            {"name": "Wheel Alignment", "description": "Four-wheel alignment", "default_price": 89.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Passenger Tyre 205/55R16", "default_price": 120.00, "unit_of_measure": "each"},
        ],
    },
    # --- Electrical & Mechanical ---
    {
        "slug": "electrician",
        "display_name": "Electrician",
        "family_slug": "electrical-mechanical",
        "icon": "zap",
        "description": "Residential and commercial electrical installation and maintenance.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Electrical Inspection", "description": "Full property electrical inspection", "default_price": 200.00, "unit_of_measure": "each"},
            {"name": "Power Point Installation", "description": "Install new power point", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "Switchboard Upgrade", "description": "Upgrade electrical switchboard", "default_price": 1200.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Power Point Double", "default_price": 12.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "hvac-technician",
        "display_name": "HVAC Technician",
        "family_slug": "electrical-mechanical",
        "icon": "thermometer",
        "description": "Heating, ventilation, and air conditioning installation and servicing.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "inventory", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Unit", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Heat Pump Service", "description": "Clean and service heat pump unit", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "Heat Pump Installation", "description": "Supply and install heat pump", "default_price": 3500.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "HVAC Filter", "default_price": 35.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "appliance-repair",
        "display_name": "Appliance Repair",
        "family_slug": "electrical-mechanical",
        "icon": "settings",
        "description": "Domestic and commercial appliance repair and servicing.",
        "recommended_modules": ["invoicing", "customers", "jobs", "inventory", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Appliance", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Diagnostic Call-Out", "description": "On-site appliance diagnostic", "default_price": 95.00, "unit_of_measure": "each"},
            {"name": "Appliance Repair", "description": "Standard appliance repair labour", "default_price": 85.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    # --- Plumbing & Gas ---
    {
        "slug": "plumber",
        "display_name": "Plumber",
        "family_slug": "plumbing-gas",
        "icon": "droplet",
        "description": "Residential and commercial plumbing installation and repairs.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Call-Out Fee", "description": "Standard call-out and first 30 minutes", "default_price": 120.00, "unit_of_measure": "each"},
            {"name": "Plumbing Labour", "description": "Plumbing labour per hour", "default_price": 95.00, "unit_of_measure": "hour"},
            {"name": "Drain Unblock", "description": "Clear blocked drain", "default_price": 180.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Tap Washer Set", "default_price": 8.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "gasfitter",
        "display_name": "Gasfitter",
        "family_slug": "plumbing-gas",
        "icon": "flame",
        "description": "Gas fitting, installation, and certification services.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "compliance_docs", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Gas Certification", "description": "Gas safety certification", "default_price": 180.00, "unit_of_measure": "each"},
            {"name": "Gas Hob Installation", "description": "Install gas cooktop", "default_price": 250.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "drainlayer",
        "display_name": "Drainlayer",
        "family_slug": "plumbing-gas",
        "icon": "layers",
        "description": "Drainage installation, repair, and CCTV inspection.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "projects", "notifications"],
        "terminology_overrides": {"asset_label": "Site", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "CCTV Drain Inspection", "description": "Camera inspection of drainage", "default_price": 350.00, "unit_of_measure": "each"},
            {"name": "Drain Repair", "description": "Excavation and drain repair", "default_price": 150.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    # --- Building & Construction ---
    {
        "slug": "builder",
        "display_name": "Builder",
        "family_slug": "building-construction",
        "icon": "hard-hat",
        "description": "Residential and commercial building, renovations, and new builds.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "projects", "time_tracking", "expenses", "progress_claims", "variations", "notifications"],
        "terminology_overrides": {"asset_label": "Site", "work_unit_label": "Job", "customer_label": "Client", "line_item_labour": "Labour"},
        "default_services": [
            {"name": "Building Labour", "description": "General building labour", "default_price": 85.00, "unit_of_measure": "hour"},
            {"name": "Project Management", "description": "Project management and supervision", "default_price": 95.00, "unit_of_measure": "hour"},
        ],
        "default_products": [
            {"name": "Framing Timber 90x45", "default_price": 8.50, "unit_of_measure": "metre"},
        ],
    },
    {
        "slug": "carpenter",
        "display_name": "Carpenter",
        "family_slug": "building-construction",
        "icon": "hammer",
        "description": "Carpentry, joinery, and woodworking services.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "notifications"],
        "terminology_overrides": {"asset_label": "Site", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Carpentry Labour", "description": "Carpentry labour per hour", "default_price": 80.00, "unit_of_measure": "hour"},
            {"name": "Custom Joinery", "description": "Custom joinery fabrication", "default_price": 95.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    {
        "slug": "roofer",
        "display_name": "Roofer",
        "family_slug": "building-construction",
        "icon": "home",
        "description": "Roofing installation, repair, and maintenance.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "inventory", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Roof Inspection", "description": "Full roof inspection and report", "default_price": 250.00, "unit_of_measure": "each"},
            {"name": "Roof Repair", "description": "Roof repair labour", "default_price": 90.00, "unit_of_measure": "hour"},
        ],
        "default_products": [
            {"name": "Roofing Iron (per sheet)", "default_price": 45.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "painter",
        "display_name": "Painter & Decorator",
        "family_slug": "building-construction",
        "icon": "paintbrush",
        "description": "Interior and exterior painting and decorating.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Interior Painting", "description": "Interior painting per room", "default_price": 450.00, "unit_of_measure": "each"},
            {"name": "Exterior Painting", "description": "Exterior painting labour", "default_price": 75.00, "unit_of_measure": "hour"},
        ],
        "default_products": [
            {"name": "Paint (10L)", "default_price": 95.00, "unit_of_measure": "each"},
        ],
    },
    # --- Landscaping & Outdoor ---
    {
        "slug": "landscaper",
        "display_name": "Landscaper",
        "family_slug": "landscaping-outdoor",
        "icon": "tree",
        "description": "Landscape design, garden construction, and outdoor living.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "projects", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Garden Design Consultation", "description": "On-site design consultation", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "Landscaping Labour", "description": "General landscaping labour", "default_price": 65.00, "unit_of_measure": "hour"},
        ],
        "default_products": [
            {"name": "Garden Soil (m³)", "default_price": 85.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "arborist",
        "display_name": "Arborist",
        "family_slug": "landscaping-outdoor",
        "icon": "axe",
        "description": "Tree surgery, removal, and maintenance.",
        "recommended_modules": ["invoicing", "customers", "jobs", "quotes", "time_tracking", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Tree Removal", "description": "Tree felling and removal", "default_price": 500.00, "unit_of_measure": "each"},
            {"name": "Tree Pruning", "description": "Tree pruning and shaping", "default_price": 250.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "lawn-mowing",
        "display_name": "Lawn Mowing & Garden Maintenance",
        "family_slug": "landscaping-outdoor",
        "icon": "leaf",
        "description": "Regular lawn mowing, garden maintenance, and property upkeep.",
        "recommended_modules": ["invoicing", "customers", "recurring", "scheduling", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Lawn Mow - Standard", "description": "Standard residential lawn mow", "default_price": 50.00, "unit_of_measure": "each"},
            {"name": "Garden Tidy", "description": "Weeding, edging, and general tidy", "default_price": 65.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    # --- Cleaning & Facilities ---
    {
        "slug": "commercial-cleaning",
        "display_name": "Commercial Cleaning",
        "family_slug": "cleaning-facilities",
        "icon": "sparkles",
        "description": "Office, retail, and commercial premises cleaning.",
        "recommended_modules": ["invoicing", "customers", "recurring", "scheduling", "staff", "notifications"],
        "terminology_overrides": {"asset_label": "Premises", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Office Clean - Standard", "description": "Standard office cleaning", "default_price": 120.00, "unit_of_measure": "each"},
            {"name": "Deep Clean", "description": "Deep cleaning service", "default_price": 350.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "residential-cleaning",
        "display_name": "Residential Cleaning",
        "family_slug": "cleaning-facilities",
        "icon": "home",
        "description": "House cleaning, end-of-tenancy, and domestic services.",
        "recommended_modules": ["invoicing", "customers", "recurring", "scheduling", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "House Clean - Standard", "description": "Standard house clean (2-3 bed)", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "End of Tenancy Clean", "description": "Full end-of-tenancy clean", "default_price": 450.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "pest-control",
        "display_name": "Pest Control",
        "family_slug": "cleaning-facilities",
        "icon": "bug",
        "description": "Pest inspection, treatment, and prevention services.",
        "recommended_modules": ["invoicing", "customers", "jobs", "scheduling", "bookings", "compliance_docs", "notifications"],
        "terminology_overrides": {"asset_label": "Property", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Pest Inspection", "description": "Full property pest inspection", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "General Pest Treatment", "description": "Interior and exterior pest treatment", "default_price": 280.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- IT & Technology ---
    {
        "slug": "it-support",
        "display_name": "IT Support & Managed Services",
        "family_slug": "it-technology",
        "icon": "monitor",
        "description": "IT support, managed services, and helpdesk.",
        "recommended_modules": ["invoicing", "customers", "jobs", "time_tracking", "recurring", "notifications"],
        "terminology_overrides": {"asset_label": "Device", "work_unit_label": "Ticket", "customer_label": "Client"},
        "default_services": [
            {"name": "IT Support - Hourly", "description": "Remote or on-site IT support", "default_price": 120.00, "unit_of_measure": "hour"},
            {"name": "Managed Services - Monthly", "description": "Monthly managed IT services", "default_price": 500.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "web-development",
        "display_name": "Web Development",
        "family_slug": "it-technology",
        "icon": "code",
        "description": "Website design, development, and maintenance.",
        "recommended_modules": ["invoicing", "customers", "projects", "time_tracking", "quotes", "recurring", "notifications"],
        "terminology_overrides": {"asset_label": "Project", "work_unit_label": "Task", "customer_label": "Client"},
        "default_services": [
            {"name": "Web Development", "description": "Web development per hour", "default_price": 150.00, "unit_of_measure": "hour"},
            {"name": "Website Hosting - Monthly", "description": "Monthly website hosting", "default_price": 30.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "computer-repair",
        "display_name": "Computer Repair",
        "family_slug": "it-technology",
        "icon": "laptop",
        "description": "Computer and device repair, upgrades, and data recovery.",
        "recommended_modules": ["invoicing", "customers", "jobs", "inventory", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Device", "work_unit_label": "Job", "customer_label": "Customer"},
        "default_services": [
            {"name": "Diagnostic Fee", "description": "Device diagnostic and assessment", "default_price": 60.00, "unit_of_measure": "each"},
            {"name": "Repair Labour", "description": "Repair labour per hour", "default_price": 95.00, "unit_of_measure": "hour"},
        ],
        "default_products": [
            {"name": "SSD 500GB", "default_price": 89.00, "unit_of_measure": "each"},
        ],
    },
    # --- Creative & Professional Services ---
    {
        "slug": "graphic-designer",
        "display_name": "Graphic Designer",
        "family_slug": "creative-professional",
        "icon": "palette",
        "description": "Graphic design, branding, and visual communication.",
        "recommended_modules": ["invoicing", "customers", "projects", "time_tracking", "quotes", "notifications"],
        "terminology_overrides": {"asset_label": "Project", "work_unit_label": "Task", "customer_label": "Client"},
        "default_services": [
            {"name": "Design - Hourly", "description": "Graphic design per hour", "default_price": 120.00, "unit_of_measure": "hour"},
            {"name": "Logo Design Package", "description": "Complete logo design package", "default_price": 1500.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "photographer",
        "display_name": "Photographer",
        "family_slug": "creative-professional",
        "icon": "camera",
        "description": "Photography services for events, portraits, and commercial.",
        "recommended_modules": ["invoicing", "customers", "bookings", "quotes", "notifications"],
        "terminology_overrides": {"asset_label": "Session", "work_unit_label": "Booking", "customer_label": "Client"},
        "default_services": [
            {"name": "Portrait Session", "description": "1-hour portrait photography session", "default_price": 250.00, "unit_of_measure": "each"},
            {"name": "Event Photography", "description": "Event photography per hour", "default_price": 200.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    {
        "slug": "consultant",
        "display_name": "Consultant",
        "family_slug": "creative-professional",
        "icon": "user-check",
        "description": "Business, management, and specialist consulting services.",
        "recommended_modules": ["invoicing", "customers", "projects", "time_tracking", "quotes", "expenses", "notifications"],
        "terminology_overrides": {"asset_label": "Engagement", "work_unit_label": "Task", "customer_label": "Client"},
        "default_services": [
            {"name": "Consulting - Hourly", "description": "Consulting services per hour", "default_price": 180.00, "unit_of_measure": "hour"},
            {"name": "Strategy Workshop", "description": "Half-day strategy workshop", "default_price": 1200.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Accounting Legal & Financial ---
    {
        "slug": "accountant",
        "display_name": "Accountant",
        "family_slug": "accounting-legal-financial",
        "icon": "calculator",
        "description": "Accounting, tax preparation, and financial advisory.",
        "recommended_modules": ["invoicing", "customers", "recurring", "time_tracking", "projects", "notifications"],
        "terminology_overrides": {"asset_label": "Engagement", "work_unit_label": "Task", "customer_label": "Client"},
        "default_services": [
            {"name": "Tax Return Preparation", "description": "Individual or business tax return", "default_price": 350.00, "unit_of_measure": "each"},
            {"name": "Bookkeeping - Monthly", "description": "Monthly bookkeeping service", "default_price": 500.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "lawyer",
        "display_name": "Lawyer / Solicitor",
        "family_slug": "accounting-legal-financial",
        "icon": "scale",
        "description": "Legal services, conveyancing, and dispute resolution.",
        "recommended_modules": ["invoicing", "customers", "time_tracking", "projects", "compliance_docs", "notifications"],
        "terminology_overrides": {"asset_label": "Matter", "work_unit_label": "Task", "customer_label": "Client", "line_item_labour": "Professional Fees"},
        "default_services": [
            {"name": "Legal Consultation", "description": "Initial legal consultation", "default_price": 250.00, "unit_of_measure": "hour"},
            {"name": "Conveyancing", "description": "Property conveyancing", "default_price": 1200.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "financial-advisor",
        "display_name": "Financial Advisor",
        "family_slug": "accounting-legal-financial",
        "icon": "trending-up",
        "description": "Financial planning, investment advice, and insurance.",
        "recommended_modules": ["invoicing", "customers", "recurring", "compliance_docs", "notifications"],
        "terminology_overrides": {"asset_label": "Portfolio", "work_unit_label": "Review", "customer_label": "Client"},
        "default_services": [
            {"name": "Financial Review", "description": "Comprehensive financial review", "default_price": 500.00, "unit_of_measure": "each"},
            {"name": "Advisory Fee - Monthly", "description": "Ongoing advisory retainer", "default_price": 300.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Health & Wellness ---
    {
        "slug": "physiotherapist",
        "display_name": "Physiotherapist",
        "family_slug": "health-wellness",
        "icon": "activity",
        "description": "Physiotherapy, rehabilitation, and sports injury treatment.",
        "recommended_modules": ["invoicing", "customers", "bookings", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Patient Record", "work_unit_label": "Appointment", "customer_label": "Patient"},
        "default_services": [
            {"name": "Initial Assessment", "description": "Initial physiotherapy assessment", "default_price": 90.00, "unit_of_measure": "each"},
            {"name": "Follow-Up Session", "description": "Follow-up treatment session", "default_price": 65.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "personal-trainer",
        "display_name": "Personal Trainer",
        "family_slug": "health-wellness",
        "icon": "dumbbell",
        "description": "Personal training, fitness coaching, and group classes.",
        "recommended_modules": ["invoicing", "customers", "bookings", "scheduling", "recurring", "notifications"],
        "terminology_overrides": {"asset_label": "Program", "work_unit_label": "Session", "customer_label": "Client"},
        "default_services": [
            {"name": "Personal Training Session", "description": "1-hour personal training", "default_price": 80.00, "unit_of_measure": "each"},
            {"name": "Group Class", "description": "Group fitness class", "default_price": 25.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "massage-therapist",
        "display_name": "Massage Therapist",
        "family_slug": "health-wellness",
        "icon": "hand",
        "description": "Therapeutic massage, sports massage, and relaxation.",
        "recommended_modules": ["invoicing", "customers", "bookings", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Session", "work_unit_label": "Appointment", "customer_label": "Client"},
        "default_services": [
            {"name": "Relaxation Massage (60min)", "description": "60-minute relaxation massage", "default_price": 90.00, "unit_of_measure": "each"},
            {"name": "Deep Tissue Massage (60min)", "description": "60-minute deep tissue massage", "default_price": 110.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Food & Hospitality ---
    {
        "slug": "restaurant",
        "display_name": "Restaurant / Cafe",
        "family_slug": "food-hospitality",
        "icon": "utensils",
        "description": "Restaurants, cafes, and dining establishments.",
        "recommended_modules": ["invoicing", "customers", "pos", "inventory", "tables", "kitchen_display", "tipping", "staff", "scheduling", "bookings", "notifications"],
        "terminology_overrides": {"asset_label": "Table", "work_unit_label": "Order", "customer_label": "Guest", "line_item_service": "Menu Item"},
        "default_services": [],
        "default_products": [
            {"name": "Coffee", "default_price": 5.00, "unit_of_measure": "each"},
            {"name": "Main Course", "default_price": 28.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "catering",
        "display_name": "Catering",
        "family_slug": "food-hospitality",
        "icon": "chef-hat",
        "description": "Event catering, corporate catering, and food services.",
        "recommended_modules": ["invoicing", "customers", "quotes", "jobs", "inventory", "staff", "scheduling", "notifications"],
        "terminology_overrides": {"asset_label": "Event", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Catering - Per Head", "description": "Standard catering per person", "default_price": 45.00, "unit_of_measure": "each"},
            {"name": "Event Setup", "description": "Event setup and pack-down", "default_price": 500.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "food-truck",
        "display_name": "Food Truck / Mobile Food",
        "family_slug": "food-hospitality",
        "icon": "truck",
        "description": "Mobile food vendors, food trucks, and market stalls.",
        "recommended_modules": ["invoicing", "customers", "pos", "inventory", "tipping", "notifications"],
        "terminology_overrides": {"asset_label": "Location", "work_unit_label": "Order", "customer_label": "Customer"},
        "default_services": [],
        "default_products": [
            {"name": "Combo Meal", "default_price": 15.00, "unit_of_measure": "each"},
        ],
    },
    # --- Retail ---
    {
        "slug": "general-retail",
        "display_name": "General Retail",
        "family_slug": "retail",
        "icon": "shopping-bag",
        "description": "General retail stores and shops.",
        "recommended_modules": ["invoicing", "customers", "pos", "inventory", "ecommerce", "loyalty", "notifications"],
        "terminology_overrides": {"asset_label": "Product", "work_unit_label": "Sale", "customer_label": "Customer"},
        "default_services": [],
        "default_products": [],
    },
    {
        "slug": "specialty-retail",
        "display_name": "Specialty Retail",
        "family_slug": "retail",
        "icon": "gift",
        "description": "Specialty and niche retail stores.",
        "recommended_modules": ["invoicing", "customers", "pos", "inventory", "ecommerce", "loyalty", "notifications"],
        "terminology_overrides": {"asset_label": "Product", "work_unit_label": "Sale", "customer_label": "Customer"},
        "default_services": [],
        "default_products": [],
    },
    # --- Hair Beauty & Personal Care ---
    {
        "slug": "hairdresser",
        "display_name": "Hairdresser / Barber",
        "family_slug": "hair-beauty-personal-care",
        "icon": "scissors",
        "description": "Hair cutting, styling, colouring, and barbering.",
        "recommended_modules": ["invoicing", "customers", "pos", "bookings", "scheduling", "inventory", "loyalty", "tipping", "notifications"],
        "terminology_overrides": {"asset_label": "Client Profile", "work_unit_label": "Appointment", "customer_label": "Client"},
        "default_services": [
            {"name": "Men's Cut", "description": "Men's haircut", "default_price": 35.00, "unit_of_measure": "each"},
            {"name": "Women's Cut & Style", "description": "Women's cut and blow-dry", "default_price": 75.00, "unit_of_measure": "each"},
            {"name": "Colour - Full Head", "description": "Full head colour treatment", "default_price": 150.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Shampoo (300ml)", "default_price": 25.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "beauty-therapist",
        "display_name": "Beauty Therapist",
        "family_slug": "hair-beauty-personal-care",
        "icon": "sparkle",
        "description": "Beauty treatments, facials, waxing, and skincare.",
        "recommended_modules": ["invoicing", "customers", "pos", "bookings", "scheduling", "inventory", "loyalty", "notifications"],
        "terminology_overrides": {"asset_label": "Client Profile", "work_unit_label": "Appointment", "customer_label": "Client"},
        "default_services": [
            {"name": "Facial Treatment", "description": "Standard facial treatment", "default_price": 95.00, "unit_of_measure": "each"},
            {"name": "Full Body Wax", "description": "Full body waxing", "default_price": 120.00, "unit_of_measure": "each"},
        ],
        "default_products": [
            {"name": "Moisturiser (50ml)", "default_price": 45.00, "unit_of_measure": "each"},
        ],
    },
    {
        "slug": "tattoo-artist",
        "display_name": "Tattoo Artist",
        "family_slug": "hair-beauty-personal-care",
        "icon": "pen-tool",
        "description": "Tattoo design and application, piercing services.",
        "recommended_modules": ["invoicing", "customers", "bookings", "scheduling", "compliance_docs", "notifications"],
        "terminology_overrides": {"asset_label": "Design", "work_unit_label": "Appointment", "customer_label": "Client"},
        "default_services": [
            {"name": "Tattoo - Hourly", "description": "Tattoo application per hour", "default_price": 180.00, "unit_of_measure": "hour"},
            {"name": "Consultation", "description": "Design consultation", "default_price": 50.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Trades Support & Hire ---
    {
        "slug": "equipment-hire",
        "display_name": "Equipment Hire",
        "family_slug": "trades-support-hire",
        "icon": "tool",
        "description": "Tool and equipment hire for trades and construction.",
        "recommended_modules": ["invoicing", "customers", "inventory", "recurring", "notifications"],
        "terminology_overrides": {"asset_label": "Equipment", "work_unit_label": "Hire", "customer_label": "Customer"},
        "default_services": [
            {"name": "Equipment Hire - Daily", "description": "Daily equipment hire rate", "default_price": 150.00, "unit_of_measure": "each"},
            {"name": "Delivery & Pickup", "description": "Equipment delivery and collection", "default_price": 80.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    {
        "slug": "trade-supplies",
        "display_name": "Trade Supplies",
        "family_slug": "trades-support-hire",
        "icon": "package",
        "description": "Trade supply stores and building material suppliers.",
        "recommended_modules": ["invoicing", "customers", "pos", "inventory", "ecommerce", "purchase_orders", "notifications"],
        "terminology_overrides": {"asset_label": "Product", "work_unit_label": "Order", "customer_label": "Customer"},
        "default_services": [
            {"name": "Delivery", "description": "Local delivery service", "default_price": 50.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Freelancing & Contracting ---
    {
        "slug": "freelancer",
        "display_name": "Freelancer",
        "family_slug": "freelancing-contracting",
        "icon": "user",
        "description": "General freelancing and independent contracting.",
        "recommended_modules": ["invoicing", "customers", "time_tracking", "projects", "quotes", "expenses", "notifications"],
        "terminology_overrides": {"asset_label": "Project", "work_unit_label": "Task", "customer_label": "Client"},
        "default_services": [
            {"name": "Freelance Work - Hourly", "description": "Freelance services per hour", "default_price": 100.00, "unit_of_measure": "hour"},
        ],
        "default_products": [],
    },
    {
        "slug": "contractor",
        "display_name": "Contractor",
        "family_slug": "freelancing-contracting",
        "icon": "clipboard",
        "description": "Independent contractors and subcontractors.",
        "recommended_modules": ["invoicing", "customers", "jobs", "time_tracking", "projects", "quotes", "expenses", "compliance_docs", "notifications"],
        "terminology_overrides": {"asset_label": "Site", "work_unit_label": "Job", "customer_label": "Client"},
        "default_services": [
            {"name": "Contract Labour", "description": "Contract labour per hour", "default_price": 85.00, "unit_of_measure": "hour"},
            {"name": "Day Rate", "description": "Full day rate", "default_price": 650.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
    # --- Custom / Other (catch-all) ---
    {
        "slug": "custom-other",
        "display_name": "Custom / Other",
        "family_slug": "freelancing-contracting",
        "icon": "settings",
        "description": "For businesses that do not fit any predefined category.",
        "recommended_modules": ["invoicing", "customers", "notifications"],
        "terminology_overrides": {},
        "default_services": [
            {"name": "Service", "description": "General service", "default_price": 100.00, "unit_of_measure": "each"},
        ],
        "default_products": [],
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # Build a lookup of family slug -> family id
    families = conn.execute(sa.text("SELECT id, slug FROM trade_families")).fetchall()
    family_map = {row[1]: row[0] for row in families}

    trade_categories = sa.table(
        "trade_categories",
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("family_id", postgresql.UUID),
        sa.column("icon", sa.String),
        sa.column("description", sa.Text),
        sa.column("recommended_modules", postgresql.JSONB),
        sa.column("terminology_overrides", postgresql.JSONB),
        sa.column("default_services", postgresql.JSONB),
        sa.column("default_products", postgresql.JSONB),
        sa.column("is_active", sa.Boolean),
    )

    rows = []
    for cat in TRADE_CATEGORIES:
        family_id = family_map.get(cat["family_slug"])
        if family_id is None:
            raise ValueError(f"Trade family '{cat['family_slug']}' not found for category '{cat['slug']}'")
        rows.append({
            "slug": cat["slug"],
            "display_name": cat["display_name"],
            "family_id": family_id,
            "icon": cat["icon"],
            "description": cat["description"],
            "recommended_modules": json.dumps(cat["recommended_modules"]),
            "terminology_overrides": json.dumps(cat["terminology_overrides"]),
            "default_services": json.dumps(cat["default_services"]),
            "default_products": json.dumps(cat["default_products"]),
            "is_active": True,
        })

    op.bulk_insert(trade_categories, rows)


def downgrade() -> None:
    slugs = [cat["slug"] for cat in TRADE_CATEGORIES]
    op.execute(
        sa.text("DELETE FROM trade_categories WHERE slug = ANY(:slugs)").bindparams(
            slugs=slugs
        )
    )
