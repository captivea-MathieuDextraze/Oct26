import logging
import os
import re
import json
import time
from pathlib import Path
import psycopg2
from datetime import timedelta
from odoo.fields import Date
from . import cap_api_call
from odoo import models, fields, api, tools, SUPERUSER_ID
from odoo.tools import BinaryBytes
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from .prompts import base_prompts
from .prompts import image_prompts
from .prompts import module_prompts
from functools import reduce

_logger = logging.getLogger(__name__)
MISTRAL_SMALL = "mistral-small-latest"


class DemoData(models.Model):
    _name = "demo.data"
    _description = "Generate Demo data and load it to the database"

    def _default_api_key(self):
        return self.env["api.key"].search([], limit=1, order="id desc").id

    name = fields.Char(
        string="Company Name",
        required=True,
        help="The name of the company which you want to generate data for",
        copy=False,
    )

    is_active = fields.Boolean(default=False)
    email = fields.Char(
        string="Email", help="The email that will be defined on creation of the company"
    )
    city = fields.Char(
        string="City",
        help="The company made will be based in this city. Its customers and suppliers may also be in this city or around",
    )
    logo = fields.Binary(string="Company Logo", readonly=False)
    lang = fields.Selection(
        string="Language",
        selection=[("en_US", "English (US)"), ("fr_FR", "French / Français")],
        default="fr_FR",
    )
    country_id = fields.Many2one(
        "res.country",
        string="Country",
        help="The company created will be based in this country and its customers will most likely be based there as well",
        required=True,
    )
    api_key_id = fields.Many2one(
        "api.key",
        string="API Key",
        required=True,
        default=_default_api_key,
        help="Generate a Mistral AI Api key to put here",
    )
    demo_date = fields.Date(
        string="Demo Date",
        required=True,
        default=datetime.today(),
        help='The model will consider this day as "today" when generating data',
    )
    website_url = fields.Char("Company Website", help="The website of the company")
    ai_info = fields.Boolean("Generate Info", help="Whether to generate company info with AI or not")
    company_id = fields.Many2one("res.company")
    linked_action_ids = fields.One2many(
        "module.load.action", "demo_data_id", string="Linked Actions", readonly=True
    )
    # Modules to install data for booleans
    bool_company_restricted = fields.Boolean(
        default=True,
        string="Product and contacts restricted to the company",
        help="Whether the generated data is shown only when the company is selected or not",
    )
    ###### NOT SHOWN ######
    base = fields.Boolean(default=True, readonly=True)
    product = fields.Boolean(default=True, readonly=True)
    account = fields.Boolean(default=True, readonly=True)
    contacts = fields.Boolean(default=True, readonly=True)
    #######################

    accountant = fields.Boolean(string="Accounting")
    crm = fields.Boolean(string="CRM")
    stock = fields.Boolean(string="Inventory")
    sale_management = fields.Boolean(string="Sales")
    purchase = fields.Boolean(string="Purchase")
    hr = fields.Boolean(string="Employees")
    website = fields.Boolean(string="Website")
    website_sale = fields.Boolean(string="Ecommerce")
    project = fields.Boolean(string="Project")
    timesheet_grid = fields.Boolean(string="Timesheets", compute="_compute_project_dependencies",store=True)
    mrp = fields.Boolean(string="Manufacturing")
    quality_control = fields.Boolean(string="Quality Control", compute="_compute_mrp_dependencies",store=True)
    mrp_plm = fields.Boolean(string="PLM",compute="_compute_mrp_dependencies",store=True)
    marketing_automation = fields.Boolean(string="Marketing Automation")
    hr_expense = fields.Boolean(string="Expenses")
    hr_recruitment = fields.Boolean(string="Recruitment")
    hr_holidays = fields.Boolean(string="Time off")
    helpdesk = fields.Boolean(string="Helpdesk")
    planning_field_service = fields.Boolean(string="Field Service Management")
    planning = fields.Boolean(string="Planning", compute="_compute_project_dependencies",store=True)
    helpdesk_timesheet = fields.Boolean(string="Helpdesk Timesheets", compute="_compute_helpdesk_dependencies",store=True)
    event = fields.Boolean(string="Events")
    knowledge = fields.Boolean(string="Knowledge")
    point_of_sale = fields.Boolean(string="Point of Sale")

    @api.depends("mrp", "quality_control", "mrp_plm")
    def _compute_mrp_dependencies(self):
        for record in self:
            record.quality_control = True if record.mrp and not record.quality_control else False
            record.mrp_plm = True if record.mrp and not record.mrp_plm else False


    @api.onchange("mrp", "stock", "purchase")
    def _onchange_mrp_dependencies(self):
        for record in self:
            # Necessary to separate the conditions to prevent infinite recursion
            if record.mrp and not record.stock:
                record.stock = True
            if record.mrp and not record.purchase:
                record.purchase = True

    @api.onchange("hr", "planning_field_service")
    def _onchange_field_service_dependencies(self):
        for record in self:
            if record.planning_field_service and not record.hr:
                record.hr = True
                record.nb_employees = 5

    @api.onchange("project", "hr", "sale_management", "planning_field_service", "purchase")
    def _onchange_project_dependencies(self):
        for record in self:
            if record.project and not record.hr:
                record.hr = True
                record.nb_employees = 5

            if record.project and not record.sale_management:
                record.sale_management = True

            if record.project and not record.planning_field_service:
                record.planning_field_service = True

            if record.project and not record.purchase:
                record.purchase = True

    @api.depends("project", "timesheet_grid", "planning")
    def _compute_project_dependencies(self):
        for record in self:
            record.timesheet_grid = True if record.project and not record.timesheet_grid else False
            record.planning = True if record.project and not record.planning else False

    @api.depends("helpdesk", "helpdesk_timesheet")
    def _compute_helpdesk_dependencies(self):
        for record in self:
            if record.helpdesk and not record.helpdesk_timesheet:
                record.helpdesk_timesheet = True
            else:
                record.helpdesk_timesheet = False

    @api.onchange("helpdesk","hr")
    def _onchange_helpdesk(self):
        for record in self:
            if record.helpdesk and not record.hr:
                record.hr = True
                record.nb_employees = 10

    @api.onchange("event","hr","sale_management")
    def _onchange_event(self):
        for record in self:
            if record.event and not record.hr:
                record.hr = True
                record.nb_employees = 10

            if record.event and not record.sale_management:
                record.sale_management = True


    @api.onchange("marketing_automation","hr")
    def _onchange_marketing_automation(self):
        for record in self:
            if record.marketing_automation and not record.hr:
                record.hr = True
                record.nb_employees = 5

            if record.marketing_automation and not record.crm:
                record.crm = True

            if record.marketing_automation and not record.sale_management:
                record.sale_management = True

            if record.marketing_automation and not record.website_sale:
                record.website_sale = True

    def write(self, vals):
        old_demo_dates = {rec.id: rec.demo_date for rec in self} if "demo_date" in vals else {}

        res = super(DemoData, self).write(vals)

        tracked_fields = {"city", "business_sector", "average_customer", "influence"}
        tracked_fields_changed = bool(tracked_fields.intersection(vals))
        ai_generated = self.env.context.get("ai_generated")

        for record in self:
            if tracked_fields_changed and not ai_generated:
                record.ai_info = False

            if old_demo_dates:
                old_date = old_demo_dates.get(record.id)
                new_date = record.demo_date
                if old_date and new_date:
                    date_diff = (new_date - old_date).days
                    activities = self.env["mail.activity"].with_company(record.company_id).search([])
                    for activity in activities:
                        activity.date_deadline = activity.date_deadline + timedelta(days=date_diff)

        return res


    @api.onchange("hr_holidays","hr")
    def _onchange_hr_holidays(self):
        for record in self:
            if record.hr_holidays and not record.hr:
                record.hr = True
                record.nb_employees = 5

    @api.onchange("hr","crm")
    def _onchange_crm(self):
        for record in self:
            if record.crm and not record.hr:
                record.hr = True
                record.nb_employees = 5


    @api.onchange("event","hr","sale_management")
    def _onchange_event(self):
        for record in self:
            if record.event and not record.hr:
                record.hr = True
                record.nb_employees = 10

            if record.event and not record.sale_management:
                record.sale_management = True


    @api.onchange("marketing_automation","hr","sale_management","crm","website_sale")
    def _onchange_marketing_automation(self):
        for record in self:
            if record.marketing_automation and not record.hr:
                record.hr = True
                record.nb_employees = 5

            if record.marketing_automation and not record.crm:
                record.crm = True

            if record.marketing_automation and not record.sale_management:
                record.sale_management = True

            if record.marketing_automation and not record.website_sale:
                record.website_sale = True


    @api.onchange("hr_recruitment","hr")
    def _onchange_hr_recruitment(self):
        for record in self:
            if record.hr_recruitment and not record.hr:
                record.hr = True
                record.nb_employees = 5


    nb_employees = fields.Integer(
        string="Number of Employees (Approximately)", default=1
    )
    bool_gen_employees_pictures = fields.Boolean(
        string="Generate pictures for employees (Only for Real demonstration, it's expensive)", default=False
    )

    percent_employees_pictures = fields.Float(
        string="Percentage of Pictures", default=0.1
    )

    bool_gen_product_pictures = fields.Boolean(
        string="Generate pictures for products (Only for Real demonstration, it's expensive)", default=False
    )

    percent_product_pictures = fields.Float(
        string="Percentage of Product Pictures", default=0.1
    )

    _unique_company_name = models.Constraint(
            "UNIQUE(name)",
            "The company name must be unique",
        )
    _check_percent_employees_pictures = models.Constraint(
            "CHECK(percent_employees_pictures >= 0)",
            "The percentage must be positive",
        )
    _check_percent_inferior = models.Constraint(
            "CHECK(percent_employees_pictures <= 1)",
            "The percentage cannot be over 100",
        )
    _check_percent_product_pictures = models.Constraint(
        "CHECK(percent_product_pictures >= 0)",
        "The percentage must be positive",
    )
    _check_product_percent_inferior = models.Constraint(
        "CHECK(percent_product_pictures <= 1)",
        "The percentage cannot be over 100",
    )

    @api.onchange("hr")
    def _onchange_hr(self):
        if not self.hr and self.nb_employees == 1:
            self.nb_employees = -1

    @api.constrains("nb_employees")
    def _check_nb_employees(self):
        for record in self:
            if record.nb_employees <= 0 and record.hr:
                raise ValidationError("Number of employees must be positive")

    mistral_model = fields.Char(
        help="To generate the data, we use the mistral-small model.",
        default="mistral-large-4",
        readonly=True,
        string="Mistral Model",
    )

    # Informations supplémentaires sur l'entreprise:
    business_sector = fields.Char(
        string="Business Sector",
        default="",
        help="A description of the company's activity and services",
    )
    customer_individual = fields.Boolean(string="Individual", default=False)
    customer_professional = fields.Boolean(string="Professional", default=True)
    influence = fields.Char(
        default="", help="The area which the company covers with its services"
    )
    average_customer = fields.Char(
        string="Customer Types",
        default="",
        help="Which type of customers the company usually deals with",
    )

    is_company_created = fields.Boolean(default=False, copy=False, readonly=True)


    @api.depends("name")
    def _compute_data_path(self):
        path = os.path.join(
            os.path.dirname(tools.config.filestore(self.env.cr.dbname)),
            (self.name).lower().replace(" ", "_").strip(),
        )
        if not os.path.exists(path):
            os.mkdir(path)
        self.data_path = path

    data_path = fields.Char(readonly=True, copy=False)

    def _synthesize_info(self) -> str:
        business_string = (

            ("\nBusiness sector: " + self.business_sector)
            if self.business_sector
            else ""
        )
        customer_string = (
            "\n"
            + "Customer Types: "
            + (
                ("Individual customers" + " and " if self.customer_professional else "")
                if self.customer_individual
                else ""
            )
            + ("Professional customers" if self.customer_professional else "")
        )
        influence_string = (
            ("\n" + "Market Influence " + self.influence) if self.influence else ""
        )
        average_customer_string = (
            ("\n" + "Customer profile: " + self.average_customer)
            if self.average_customer
            else ""
        )
        return (
            business_string
            + customer_string
            + influence_string
            + average_customer_string
        )

    generation_in_progress = fields.Boolean(default=False)

    def _more_modules(self):
        """Creates the module actions when called by 'create_items()'
        Will only create the actions for which the dependent_module is checked and the dependent_var too (if exists)"""

        actions_to_load = [
            {
                "name": "General Information",
                "prompt": base_prompts.INFORMATION_PROMPT_1,
                "file_to_load": "general_information.txt",
                "dependent_module": "base",
            },
            {
                "name": "Background Image",
                "prompt": image_prompts.BACKGROUND_PROMPT,
                "file_to_load": "background_image.txt",
                "dependent_module": "base",
            },
            {
                "name": "Products",
                "prompt": base_prompts.PRODUCTS_PROMPT,
                "file_to_load": "customer_products.csv;supplier_products.csv",
                "dependent_module": "account",
            },
            {
                "name": "Products Pictures",
                "prompt": image_prompts.PRODUCT_PICTURES_PROMPT,
                "dependent_module": "base",
                "dependent_var": self.bool_gen_product_pictures,
            },
            {
                "name": "Customers and Suppliers",
                "prompt": base_prompts.PARTNERS_PROMPT,
                "file_to_load": "customers.csv;suppliers.csv;log_chatter.csv",
                "dependent_module": "contacts",
            },
            {
                "name": "Customers and Suppliers: Child Contacts",
                "prompt": base_prompts.CHILD_CONTACTS_PROMPT,
                "file_to_load": "child_contacts.csv",
                "dependent_module": "contacts",
            },
            {
                "name": "Analytic Accounts",
                "prompt": base_prompts.ANALYTIC_ACCOUNTS_PROMPT,
                "file_to_load": "analytic_accounts.csv",
                "dependent_module": "account",
                "dependent_var": self.accountant,
            },
            {
                "name": "Customer and Supplier bills",
                "prompt": base_prompts.BILLS_PROMPT,
                "file_to_load": "customer_bills.csv;supplier_bills.csv;followups.csv",
                "dependent_module": "account",
            },
            {
                "name": "Assets",
                "prompt": base_prompts.ASSETS_PROMPT,
                "file_to_load": "assets.csv",
                "dependent_module": "accountant",
                "dependent_var": self.accountant,
            },
            {
                "name": "Employees",
                "prompt": module_prompts.HR_PROMPT,
                "file_to_load": "departments.csv;employees.csv",
                "dependent_module": "hr",
                "var": "\n Employees and Departments: The departments must be realistic for the industry and the employees organigram should be realistic",
            },
            {
                "name": "Employees Pictures",
                "dependent_module": "hr",
                "prompt": image_prompts.HR_PICTURES_PROMPT,
                "dependent_var": self.bool_gen_employees_pictures,
            },
            {
                "name": "CRM",
                "prompt": module_prompts.CRM_PROMPT,
                "file_to_load": "crm_tags.csv;crm_leads.csv;crm_activities.csv",
                "dependent_module": "crm",
                "var": "\n- CRM Leads: The CRM leads must be realistic, and the partners should be the same as the previously created partners",
            },
            {
                "name": "Inventory",
                "prompt": module_prompts.INVENTORY_PROMPT,
                "file_to_load": "stock.csv;replenishments.csv",
                "dependent_module": "stock",
                "var": "\n- Inventory Adjustments: The products added to the inventory must be only physical goods, and the quantities of each product must be realistic for the company to have in stock",
            },
            {
                "name": "Sales",
                "prompt": module_prompts.SALES_PROMPT,
                "file_to_load": "sales.csv;quotation_templates.csv",
                "dependent_module": "sale_management",
                "var": "\n- Customer Sales: The customer sales must correspond to existing customer products and previously created customers ",
            },
            {
                "name": "Purchase",
                "prompt": module_prompts.PURCHASE_PROMPT,
                "file_to_load": "purchase.csv",
                "dependent_module": "purchase",
                "var": "\n- Supplier Purchases: The purchases must correspond to existing supplier products and previously created suppliers, and the transactions must be realistic—meaning the suppliers should logically sell these products, and the company should plausibly purchase them.",
            },
            {
                "name": "Manufacture",
                "dependent_module": "mrp",
                "file_to_load": "component_products.csv;bom.csv",
                "prompt": module_prompts.MRP_COMPONENTS_PROMPT,
                "var": "\n Manufacture: Some of the customer products created must be realistic to be manufactured by the company to be sold",
            },
            {
                "name": "Manufacture: Bills of Materials",
                "dependent_module": "mrp",
                "file_to_load": "bom_components.csv",
                "prompt": module_prompts.MRP_BOM_PROMPT,
            },
            {
                "name": "Manufacture: Work Centers",
                "dependent_module": "mrp",
                "file_to_load": "work_centers.csv",
                "prompt": module_prompts.WORK_CENTERS_PROMPT,
            },
            {
                "name": "Manufacture: BOM Operations",
                "dependent_module": "mrp",
                "file_to_load": "work_orders.csv",
                "prompt": module_prompts.WORK_ORDERS_PROMPT,
            },
            {
                "name": "Manufacturing Orders",
                "dependent_module": "mrp",
                "file_to_load": "manufacturing_orders.csv",
                "prompt": module_prompts.MANUFACTURING_ORDERS_PROMPT,
            },
            {
                "name": "Manufacturing: BOM Operation Instructions",
                "dependent_module": "mrp",
                "file_to_load": "operation_instructions.csv",
                "prompt": module_prompts.BOM_OPERATION_INSTRUCTIONS,
            },
            {
                "name": "Point of Sale: Products",
                "dependent_module": "point_of_sale",
                "file_to_load": "pos_products.csv;pos_combo_items.csv",
                "prompt": module_prompts.POS_PRODUCTS_PROMPT,
                "dependent_var": self.point_of_sale,
            },
            {
                "name": "Point of Sale: Orders",
                "dependent_module": "point_of_sale",
                "file_to_load": "pos_session.csv;pos_orders.csv",
                "prompt": module_prompts.POS_PROMPT,
                "dependent_var": self.point_of_sale,
            },
            {
                "name": "Project and Tasks",
                "dependent_module": "project",
                "file_to_load": "projects.csv;tasks.csv;timesheets.csv",
                "prompt": module_prompts.PROJECT_AND_TASKS_PROMPT,
                "dependent_var": self.project,
            },
            {
                "name": "Field Service",
                "dependent_module": "planning_field_service",
                "file_to_load": "field_service_tasks.csv;field_service_timesheets.csv",
                "prompt": module_prompts.FIELD_SERVICE_PROMPT,
                "dependent_var": self.planning_field_service,
            },
            {
                "name": "Field Service: Worksheets",
                "dependent_module": "planning_field_service",
                "file_to_load": "fsm_worksheets.csv",
                "prompt": module_prompts.FIELD_SERVICE_WORKSHEET_PROMPT,
                "dependent_var": self.planning_field_service,
            },
            {
                "name": "Helpdesk Tickets",
                "dependent_module": "helpdesk",
                "file_to_load": "helpdesk_team.csv;helpdesk_ticket.csv;helpdesk_timesheet.csv",
                "prompt": module_prompts.HELPDESK_PROMPT,
                "dependent_var": self.helpdesk,
            },
            {
                "name": "Event: Events and Venues",
                "dependent_module": "event",
                "file_to_load": "event_venues.csv;events.csv;event_tickets.csv",
                "prompt": module_prompts.EVENTS_PROMPT,
                "dependent_var": self.event,
            },
            {
                "name": "Event: Registrations and Ticket sales",
                "dependent_module": "event",
                "file_to_load": "event_registrations.csv",
                "prompt": module_prompts.EVENT_TICKETS_REGISTRATION_PROMPT,
                "dependent_var": self.event,
            },
            {
                "name": "Marketing Automation: Campaigns",
                "dependent_module": "marketing_automation",
                "file_to_load": "mailing_list.csv",
                "prompt": module_prompts.MARKETING_AUTOMATION_PROMPT,
                "dependent_var": self.marketing_automation,
            },
            {
                "name": "Knowledge: Articles",
                "dependent_module": "knowledge",
                "file_to_load": "knowledge_articles.csv",
                "prompt": module_prompts.KNOWLEDGE_ARTICLE_PROMPT,
                "dependent_var": self.knowledge,
            },
            {
                "name": "Time Off: Requests and Allocations",
                "dependent_module": "hr_holidays",
                "file_to_load": "mandate_days.csv;time_off_allocation.csv;time_off_requests.csv",
                "prompt": module_prompts.TIME_OFF_REQUESTS_PROMPT,
                "dependent_var": self.hr_holidays,
            },
            {
                "name": "Recruitment: Job Positions and Applications",
                "dependent_module": "hr_recruitment",
                "file_to_load": "job_positions.csv;job_applications.csv",
                "prompt": module_prompts.RECRUITMENT_PROMPT,
                "dependent_var": self.hr_recruitment,
            },
            {
                "name": "Generate Invoice PDF",
                "prompt": image_prompts.PDF_PROMPT,
                "dependent_module": "accountant",
                "dependent_var": self.accountant,
            },
            {
                "name": "Generate Header PDF",
                "prompt": image_prompts.HEADER_PDF_PROMPT,
                "dependent_module": "sale_management",
            },
            {
                "name": "Generate Footer PDF",
                "prompt": image_prompts.FOOTER_PDF_PROMPT,
                "dependent_module": "sale_management",
            },
            {
                "name": "Website",
                "dependent_module": "website",
                "dependent_var": self.website,
            },
        ]
        company_id = self.env["res.company"].search([("name", "=", self.name)], limit=1).id
        return_var = ""
        actions_to_create = []
        for action in actions_to_load:
            if "dependent_var" in action and not action["dependent_var"]:
                continue
            if not self[action["dependent_module"]]:
                continue
            if "var" in action:
                return_var += action["var"]

            action_vals = {k: v for k, v in action.items() if k not in ("dependent_var", "var")}
            action_vals.update({"nb_tries": 0, "state": "in_line", "demo_data_id": self.id})
            actions_to_create.append(action_vals)

        if actions_to_create:
            self.env["module.load.action"].with_company(company_id).create(actions_to_create)

        return return_var


    module_list = [
        "accountant",
        "contacts",
        "crm",
        "sale_management",
        "purchase",
        "stock",
        "hr",
        "website",
        "website_sale",
        "project",
        "timesheet_grid",
        "planning",
        "mrp",
        "quality_control",
        "mrp_plm",
        "point_of_sale",
        "marketing_automation",
        "hr_expense",
        "hr_recruitment",
        "hr_holidays",
        "helpdesk",
        "helpdesk_timesheet",
        "event",
        "knowledge"
    ]

    def _install_modules(self):
        to_install = set([m for m in self.module_list if self[m]])

        to_install.update(["base_geolocalize","account_followup"])
        if self.planning_field_service:
            to_install.update(["planning_field_service", "planning_field_service_worksheet"])
        if self.accountant:
            to_install.update(["account_asset", "account_budget","account_followup"])
        if self.purchase:
            to_install.add("purchase_stock")
        if self.project:
            to_install.update(["sale_project", "planning_field_service", "planning_field_service_worksheet", "planning"])
        if self.helpdesk and self.stock:
            to_install.update(["helpdesk_account", "helpdesk_sale_loyalty", "helpdesk_stock", "helpdesk_repair", "planning_field_service", "planning_field_service_worksheet"])
        if self.event:
            to_install.add("event_product")
        if self.sale_management:
            to_install.add("sale_margin")
        if self.website:
            to_install.update(["theme_default", "website_sale", "website_generator", "website_generator_sale"])
        if self.stock:
            to_install.add("sale_stock")

        modules = self.env["ir.module.module"].search(
            [("name", "in", list(to_install)), ("state", "!=", "installed"), ])

        for mod in modules:
            self._immediate_install(mod)
            self._set_crons_active()

        if self.stock:
            existing_names = {w.name for w in self.env["stock.warehouse"].with_user(SUPERUSER_ID).search([])}
            warehouses_to_create = [{"name": c.name, "code": "STOCK", "company_id": c.company_id.id} for c in
                                    self.env["demo.data"].search([("company_id", "!=", False)])
                                    if c.name not in existing_names]

            if warehouses_to_create:
                self.env["stock.warehouse"].with_user(SUPERUSER_ID).create(warehouses_to_create)

    def _immediate_install(self, modules):
        """ Install ``modules`` in a fresh transaction.

        ``button_immediate_install`` locks every scheduled action with ``SELECT ... FOR UPDATE``.
        In repeatable read, that fails with a serialization error if any of them was changed
        after the current transaction's snapshot, which is always the case right after
        ``_set_crons_active`` (it commits from its own cursor). Committing first starts a new
        snapshot; ``button_immediate_install`` commits the request transaction anyway.
        """
        self.env.cr.commit()
        return modules.button_immediate_install()

    def _immediate_uninstall(self, modules):
        """ Uninstall ``modules`` in a fresh transaction, see ``_immediate_install``. """
        self.env.cr.commit()
        return modules.button_immediate_uninstall()

    def _set_crons_active(self, crons=None):
        """ Deactivate every scheduled action but ``crons``, which are activated.

        Done in its own short transaction: the cron worker keeps running (and updating) the
        scheduled actions of the modules installed meanwhile, so the same update from the long
        request transaction fails with a serialization error as soon as one of them has run.
        The jobs being run are locked by the worker: they are skipped until they are done.
        """
        keep_ids = crons.ids if crons else []
        for _attempt in range(60):
            try:
                with self.env.registry.cursor() as cr:
                    cr.execute("""
                        UPDATE ir_cron SET active = (id = ANY(%(keep)s::int[]))
                         WHERE id IN (SELECT id FROM ir_cron
                                       WHERE active != (id = ANY(%(keep)s::int[]))
                                         FOR NO KEY UPDATE SKIP LOCKED)
                    """, {"keep": keep_ids})
                    cr.execute("SELECT 1 FROM ir_cron WHERE active != (id = ANY(%s::int[])) LIMIT 1", [keep_ids])
                    if not cr.fetchone():
                        return
            except psycopg2.errors.SerializationFailure:
                pass  # a job finished while we were locking the rows
            time.sleep(0.5)

    def delete_all_items(self):
        all_records = self.env['demo.data'].search([])
        self._set_crons_active()

        all_records.write({'ai_info': False})
        records_with_company = all_records.filtered('company_id')
        records_with_company.write({'is_active': False, 'generation_in_progress': False})
        for record in records_with_company:
            path = Path(record.data_path)
            for ext in ("*.csv", "*.txt", "*.jpg", "*.pdf", "*.png"):
                for f in path.glob(ext):
                    f.unlink()

        installed_states = {"installed", "to_upgrade", "to_remove"}
        module_names = self.module_list + ["ai_agentic", "planning_field_service", "planning_field_service_worksheet"]
        module_state = {m.name: m.state for m in
                        self.env["ir.module.module"].search([("name", "in", module_names)])}

        if module_state.get("crm") in installed_states:
            self.env["crm.lead"].sudo().search([]).unlink()
        try:
            self.env["delivery.carrier"].sudo().search([]).unlink()
        except Exception:
            pass

        website = self.env["ir.module.module"].search([("name", "=","website"),("state", "!=", "uninstalled")])
        if website:
            self._immediate_uninstall(website)

        to_uninstall = [m for m in module_names if m != 'knowledge' and module_state.get(m) in installed_states]

        if self.hr_holidays:
            self._immediate_uninstall(self.env["ir.module.module"].sudo().search(
                [("name", "in", ["hr_holidays"]), ("state", "=", "installed")]))
        to_uninstall = [m for m in to_uninstall if m != "hr_holidays"]

        self.env.cr.execute("""delete from account_payment_register""")

        for mod in self.env["ir.module.module"].search([("name", "in", to_uninstall), ("state", "!=", "uninstalled")]):
            try:
                self._immediate_uninstall(mod)
            except Exception:
                _logger.warning("Could not uninstall %s", mod.name, exc_info=True)

        # the "info" alias of the leads can outlive crm (partial uninstall, crm.lead kept by another
        # module) and then makes the next crm install fail: crm_team_data.xml gives the same name to
        # the default sales team. Free the name (the alias can still be referenced by a team).
        if self.env["ir.module.module"].search([("name", "=", "crm")], limit=1).state != "installed":
            stale_aliases = self.env["mail.alias"].sudo().search(
                [("alias_name", "=", "info"), ("alias_model_id.model", "=", "crm.lead")])
            if stale_aliases:
                _logger.info("Freeing the stale crm alias(es) %s", stale_aliases.ids)
                stale_aliases.write({"alias_name": False})


        payments = self.env["account.payment"].sudo().search([])
        for payment in payments:
            payment.state = 'draft'
        payments.sudo().unlink()

        try:
            self.env["sale.order.line"].sudo().search([]).product_uom_qty = 0
            sale_orders = self.env["sale.order"].sudo().search([])
            sale_orders.write({'state': 'cancel'})
            sale_orders.unlink()
        except Exception:
            pass

        account_moves = self.env["account.move"].sudo().search([])
        account_moves.filtered(lambda m: m.state == "posted").button_draft()
        account_moves.sudo().unlink()

        self.env["res.partner"].sudo().search(
            ["|", "|", ("category_id", "like", "supplier"), ("category_id", "like", "customer"),
             ("category_id", "like", "venue"), ]).unlink()

        if self.crm:
            self.env["crm.tag"].search([]).unlink()

        loyalty_products = self.env["product.template"].sudo().search(
            ["|", ("name", "ilike", "Gift"), ("name", "ilike", "Top-up")])
        self.env["account_followup.followup.line"].sudo().search([]).unlink()
        self.env["product.combo.item"].sudo().search([]).unlink()
        self.env["product.combo"].sudo().search([]).unlink()
        self.env["knowledge.article"].search([]).unlink()
        self.env["account.analytic.line"].sudo().search([]).unlink()
        self.env["account.analytic.account"].sudo().search([]).unlink()
        # Since Odoo 20 the mail tracking done at commit reads the property definitions of the tracked
        # records: generate the pending trackings while the products still exist
        self.env.cr.flush()
        self.env["product.template"].sudo().search([("id", "not in", loyalty_products.ids)]).unlink()

        self.env["res.partner.category"].sudo().search(
            ["|", "|", ("name", "like", "customer"), ("name", "like", "supplier"),
             ("name", "like", "venue"), ]).unlink()

        self.env["module.load.action"].sudo().search([]).unlink()
        self.env["ir.attachment"].sudo().search([("company_id", "!=", 1)]).unlink()
        admin_user = self.env["res.users"].search([("id", "=", 2)])
        self.env["res.users"].search([("id", "!=", 2)]).unlink()
        company_partner_ids = self.env["res.company"].sudo().search([]).mapped("partner_id.id")
        excluded_partner_ids = company_partner_ids + [admin_user.partner_id.id]
        self.env["res.partner"].sudo().search([("id", "not in", excluded_partner_ids)]).unlink()

        self.env.cr.execute("""DELETE FROM mail_message WHERE model='product.product'
                            OR model='account.bank.statement.line' """)
        cron_refs = self.env.ref("ai.ir_cron_generate_embedding", raise_if_not_found=False)
        if cron_refs:
            self._set_crons_active(cron_refs)


    def generate_company_info(self):
        self = self.with_context(ai_generated=True)

        self.ai_info = True
        language = "French" if self.lang == "fr_FR" else "English"
        _logger.info("Starting generation for company information")

        new_message = (
            base_prompts.INFORMATION_PROMPT_2.replace("__name__", self.name)
            .replace("__today__", self.demo_date.strftime("%Y-%m-%d"))
            .replace("__country__", self.country_id.name)
            .replace("__website__", self.website_url)
            .replace("__language__", language)
            .replace("__company_information__", self._synthesize_info())
        )

        result = cap_api_call.mistral_api_call(
            MISTRAL_SMALL, new_message, self.api_key_id.name, self.lang
        )
        text = result.choices[0].message.content
        self._compute_data_path()
        base_dir = Path(self.data_path)
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "general_information.txt").write_text(text, encoding="utf-8-sig")

        _logger.info("Finished generation for company information")

        info = {}
        for match in re.findall(r"```json(.*?)```", text, re.DOTALL):
            try:
                info = json.loads(match.strip())
                break
            except Exception as e:
                _logger.warning("Invalid JSON block: %s", e)

        logo_action = self.env["module.load.action"]
        img_data, error = logo_action.download_logo(self.website_url, Path(self.data_path))
        if not error:
            logo_data = BinaryBytes(img_data)
            self.logo = logo_data
            if self.company_id:
                self.company_id.logo = logo_data

        self.write({
            "business_sector": info.get("Business sector"),
            "city": info.get("City"),
            "average_customer": info.get("Customer Types"),
            "influence": info.get("Market Influence"),
        })

    def create_company_open_wizard(self):
        if self.filtered(lambda r: not r.ai_info and not (r.business_sector and r.influence and r.average_customer)):
            raise ValidationError("When Company Details are not generated by AI, Business Sector, Influence, and Average Customer fields must be filled.")

        return {
            "name": "Create Company Wizard",
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "demo.data.wizard",
            "target": "new",
            "context": {
                "default_name": self.name,
                "default_website_url": self.website_url,
                "default_city": self.city,
                "default_country_id": self.country_id.id,
                "default_email": self.email,
                "default_logo": self.logo.to_base64() if self.logo else False,
                "default_demo_data_id": self.id,
            },
        }


    # def install_mistral_ai_module(self):
    #     mod = self.env["ir.module.module"].search([("name", "=", "connect_mistral_ai")], limit=1)
    #     if not mod or mod.state == "uninstallable":
    #         _logger.warning("connect_mistral_ai is not installable on this Odoo version, skipping the Mistral AI setup")
    #         return
    #     if mod.state not in ("installed", "to_install"):
    #         self._immediate_install(mod.sudo())
    #
    #     self.env['res.config.settings'].create({
    #         'mistral_key_enabled': True,
    #         'mistral_key': self.api_key_id.name,
    #     }).execute()
    #
    #     # Odoo 20 removed the natural language search agent and ai.agent.llm_model
    #     default_agent = self.env.ref("ai.ai_default_agent", raise_if_not_found=False)
    #     if default_agent and "llm_model" in default_agent._fields:
    #         default_agent.write({'llm_model': "mistral-medium-latest"})


    def _get_file_value(self, file_name):
        try:
            return (Path(self.data_path) / file_name).read_text(encoding="utf-8-sig")
        except Exception:
            return ""

    def get_values_dict(self):
        def _stock_products_value():
            if self.stock and self.env["ir.module.module"].search([("name", "=", "stock")], limit=1).state in (
                    "installed", "to_remove", "to_upgrade"):
                return ("Here are the pre-established quantities you have in stock for the products. Make sure the sold quantities are less than what is available in stock:\n```csv" +
                        self._get_file_value("stock.csv") + "```")
            return ""

        def _time_off_types_value(allocation_only=False):
            # time off types are hr.work.entry.type records since Odoo 20 and their names depend on the country
            if ("hr.work.entry.type" not in self.env
                    or "time_off_selectable" not in self.env["hr.work.entry.type"]._fields):
                return "[]"
            time_off_types = self.env["module.load.action"]._get_time_off_types(self.company_id)
            if allocation_only:
                time_off_types = time_off_types.filtered("requires_allocation")
            return str(time_off_types.mapped("name"))

        return {
            "__today__": self.demo_date.strftime("%Y-%m-%d"),
            "__global_prompt__": self._get_file_value("general_information.txt"),
            "__supplier_products__": self._get_file_value("supplier_products.csv"),
            "__customer_products__": self._get_file_value("customer_products.csv"),
            "__customers__": self._get_file_value("customers.csv"),
            "__suppliers__": self._get_file_value("suppliers.csv"),
            "__child_contacts__": self._get_file_value("child_contacts.csv"),
            "__customer_bills__": self._get_file_value("customer_bills.csv"),
            "__supplier_bills__": self._get_file_value("supplier_bills.csv"),
            "__bom__": self._get_file_value("bom.csv"),
            "__component_products__": self._get_file_value("component_products.csv"),
            "__bom_components__": self._get_file_value("bom_components.csv"),
            "__work_centers__": self._get_file_value("work_centers.csv"),
            "__work_orders__": self._get_file_value("work_orders.csv"),
            "__employees__": self._get_file_value("employees.csv"),
            "__inventory__": _stock_products_value(),
            "__nb_employees__": str(self.nb_employees),
            "__events__": self._get_file_value("events.csv"),
            "__departments__": self._get_file_value("departments.csv"),
            "__pos_products__": self._get_file_value("pos_products.csv"),
            "__pos_combo_items__": self._get_file_value("pos_combo_items.csv"),
            "__fsm_tasks__": self._get_file_value("field_service_tasks.csv"),
            "__fsm_timesheets__": self._get_file_value("field_service_timesheets.csv"),
            "__time_off_types__": _time_off_types_value(),
            "__allocation_time_off_types__": _time_off_types_value(allocation_only=True),
        }

    def _generate_info(self, added_modules):
        replacements = {
            "__name__": self.company_id.name,
            "__city__": self.city,
            "__website__": self.website_url,
            "__today__": self.demo_date.strftime("%Y-%m-%d"),
            "__country__": self.country_id.name,
            "__language__": "French" if self.lang == "fr_FR" else "English",
            "__company_information__": self._synthesize_info(),
            "__more_modules__": added_modules,
        }
        pattern = re.compile("|".join(map(re.escape, replacements)))
        new_message = pattern.sub(lambda m: replacements[m.group()], base_prompts.INFORMATION_PROMPT_1)

        self.env["module.load.action"].search([("name", "=", "General Information"), ("demo_data_id", "=", self.id)],
                                              limit=1).write({"prompt": new_message})

    def process_action_queue(self, number_items=3):
        _logger.warning("Executing Scheduled Action for data generation")
        if self.env["ir.cron"].search([("name", "=", "CAP - Load Demo Data"), ("state", "=", "running")]):
            _logger.error("ACTION CAP - LOAD DEMO DATA Already running")
            return False

        nb_done = 0
        for action in self.linked_action_ids:
            if action.state == 'skipped':
                continue

            if (action.state == "failed" and action.nb_tries >= 3 and action.name in
                    ["Background Image", "Products Pictures", "Employees Pictures"]):
                action.write({'state': 'skipped'})
                continue
            if nb_done >= number_items or (action.state == "failed" and action.nb_tries >= 9):
                break
            if action.state == 'ok':
                continue
            if not action.exec_action():
                break
            nb_done += 1
            # a failing action rolls back its attempts: keep the actions done before it
            self.env["ir.cron"]._commit_progress(processed=1)

        if not nb_done:
            # queue finished, or waiting for a failed action to be retried: nothing changed
            return True

        for record in self:
            if record.hr:
                all_users = self.env["res.users"].search([("company_id", "=", record.company_id.id)])

                for user in all_users:
                    self._update_user_signature(user, record)

        _logger.info("%s demo data action(s) executed", nb_done)
        if nb_done == number_items:
            return False

        _logger.warning(f"Could not execute {number_items} actions")
        return True

    def _update_user_signature(self, user, record):
        user.signature = ''
        if user.id == 2:
            user.write({'company_id': record.company_id.id})

        if user.employee_ids:
            current_user_employee_id = user.employee_ids[:1]
            user.write({
                "signature": f"""
    <div class="signature-area">
        <div id="signature" class="signature preview-signature">
            <table cellspacing="0" cellpadding="0" border="0" style="border-collapse:separate;table-layout:fixed;overflow-wrap:break-word;word-wrap:break-word;word-break:break-word;" width="100%">
                <tbody>
                    <tr>
                        <td style="width:100%;">
                            <table cellspacing="0" cellpadding="0" border="0" style="border-collapse:separate;table-layout:fixed;" width="500">
                                <tbody>
                                    <tr>
                                        <td style="padding-left:30px;vertical-align:middle;width:320px;font-family:Tahoma, Verdana, Segoe, sans-serif;" width="320">
                                            <table cellspacing="0" cellpadding="0" border="0" style="border-collapse:separate;" width="100%">
                                                <tbody>
                                                    <tr>
                                                        <td style="font-weight:bold;color:#BA131A;font-size:16px;line-height:24px;">
                                                            <p style="margin:.1px;">
                                                                <span>{user.display_name}</span>
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#714B67;text-decoration:none;font-size:13px;line-height:20px;padding-bottom:7px;border-bottom:1px solid #BA131A;">
                                                            <p style="margin:.1px;">
                                                                <span style="font-weight:bold;">
                                                                    {current_user_employee_id.job_title}
                                                                </span> | {user.company_id.name}
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#714B67;text-decoration:none;font-size:13px;line-height:20px;padding-top:7px;">
                                                            <p style="margin:.1px;">
                                                                {user.company_id.name}
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#714B67;text-decoration:none;font-size:13px;line-height:20px;padding-top:7px;">
                                                            <p style="margin:.1px;">
                                                                {user.company_id.city}
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#714B67;text-decoration:none;font-size:13px;line-height:20px;">
                                                            <p style="margin:.1px;">
                                                                {user.company_id.country_id.name}
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#212529;font-size:13px;line-height:20px;">
                                                            <p style="margin:.1px;">
                                                                <img src="https://captiveausa.icns.email/icon/fa-light-16-at-714B67.png" width="16" height="16" style="vertical-align:middle;margin-right:4px;">
                                                                <a href="mailto:{user.email}" style="color:#714B67;text-decoration:none;">
                                                                    {user.email or user.work_email}
                                                                </a>
                                                            </p>
                                                        </td>
                                                    </tr>

                                                    <tr>
                                                        <td style="color:#212529;font-size:13px;line-height:20px;">
                                                            <p style="margin:.1px;">
                                                                <img src="https://captiveausa.icns.email/icon/fa-light-16-phonealt-714B67.png" width="16" height="16" style="vertical-align:middle;margin-right:4px;">
                                                                <a href="tel:+19999999999" style="color:#714B67;text-decoration:none;">
                                                                    {user.phone or user.work_phone}
                                                                </a>
                                                            </p>
                                                        </td>
                                                    </tr>
                                                </tbody>
                                            </table>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    """
            })


    def create_items(self):
        company_id = self.env["res.company"].search([("name", "=", self.name)], limit=1)
        if not company_id:
            raise UserError("There is no company created with the name %s" % self.name)

        self.write({'company_id': company_id.id})
        company_id.write({'external_report_layout_id': self.env.ref("web.external_layout_folder").id})

        if not self.generation_in_progress:
            cron_refs = [self.env.ref("cap_DemoDataAI.ir_cron_demo_data", raise_if_not_found=False),
                         self.env.ref("ai.ir_cron_generate_embedding", raise_if_not_found=False),
                         self.env.ref("website_generator.cron_get_result", raise_if_not_found=False), ]

            crons = reduce(lambda a, b: a | b, [c for c in cron_refs if c], self.env['ir.cron'])
            self.write({'is_active': True})
            self._set_crons_active()

            self._install_modules()
            if crons:
                self._set_crons_active(crons)

            self.env["module.load.action"].search([("demo_data_id", "=", self.id)]).unlink()
            self_ctx = self.with_company(company_id)
            self_ctx._generate_info(self_ctx._more_modules())

        self.write({'generation_in_progress': True})
