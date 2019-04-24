# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import random
import string
import logging

from odoo import models, fields, api, SUPERUSER_ID, sql_db
from odoo.tools.safe_eval import test_python_expr, safe_eval
from odoo.exceptions import ValidationError
from odoo.addons.queue_job.job import job
from ..xmlrpc import rpc_auth, rpc_install_modules, rpc_code_eval

_logger = logging.getLogger(__name__)

MANDATORY_MODULES = ['auth_quick']
DEFAULT_BUILD_PYTHON_CODE = """# Available variables:
#  - env: Odoo Environment on which the action is triggered
#  - model: Odoo Model of the record on which the action is triggered; is a void recordset
#  - record: record on which the action is triggered; may be void
#  - records: recordset of all records on which the action is triggered in multi-mode; may be void
#  - time, datetime, dateutil, timezone: useful Python libraries
#  - log: log(message, level='info'): logging function to record debug information in ir.logging table
#  - Warning: Warning Exception to use with raise
# To return an action, assign: action = {{...}}
# You can specify places for variables that can be passed when creating a build like this:
# env['{{key_name_1}}'].create({{'subject': '{{key_name_2}}', }})
# but with single curly braces instead of double in places where you need pass variable\n\n\n\n"""


def random_password(len=32):
    return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(len))


class SAASTemplate(models.Model):
    _name = 'saas.template'
    _description = 'Database Template'

    name = fields.Char()
    template_demo = fields.Boolean('Install demo data', default=False)
    template_modules_domain = fields.Text(
        'Modules to install',
        help='Domain to search for modules to install after template database creation',
        default="[]")
    template_post_init = fields.Text(
        'Template Initialization',
        default=lambda s: s.env['ir.actions.server'].DEFAULT_PYTHON_CODE,
        help='Python code to be executed once db is created and modules are installed')
    build_post_init = fields.Text(
        'Build Initialization',
        default=DEFAULT_BUILD_PYTHON_CODE,
        help='Python code to be executed once build db is created from template')
    operator_ids = fields.One2many('saas.template.operator', 'template_id', string="Template operators")

    @api.constrains('template_post_init')
    def _check_python_code(self):
        for r in self.sudo():
            msg = test_python_expr(expr=r.template_post_init.strip(), mode="exec")
            if msg:
                raise ValidationError(msg)

    @api.multi
    def action_create_build(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Build',
            'res_model': 'create.build.by.template',
            'src_model': 'saas.template',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': self.env.ref('saas.create_build_by_template_wizard').id,
            'target': 'new',
            'context': {'template_id': self.id},
        }


class SAASTemplateLine(models.Model):
    _name = 'saas.template.operator'
    _description = 'Template\'s Settings for Operator'
    _rec_name = 'operator_db_name'

    template_id = fields.Many2one('saas.template', required=True)
    operator_id = fields.Many2one('saas.operator', required=True)
    password = fields.Char('DB Password')
    operator_db_name = fields.Char(required=True)
    operator_db_id = fields.Many2one('saas.db', readonly=True)
    operator_db_state = fields.Selection(related='operator_db_id.state', string='Database operator state')
    to_rebuild = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('creating', 'Database Creating'),
        ('installing_modules', 'Modules installation'),
        ('post_init', 'Extra initialization'),
        ('done', 'Ready'),

    ], default='draft')

    def preparing_template_next(self):
        template_operators = self.search([('to_rebuild', '=', True)])
        operators = template_operators.mapped('operator_id')

        # filter out operators which already have template creating
        def filter_free_operators(op):
            states = op.template_operator_ids.mapped('state')
            return all((s in ['draft', 'done'] for s in states))

        operators = operators.filtered(filter_free_operators)
        if not operators:
            # it's not a time to start
            return
        for t_op in template_operators:
            if t_op.operator_id not in operators:
                continue
            t_op._prepare_template()

            # only one template per operator
            operators -= t_op.operator_id

    def _prepare_template(self):
        for r in self:
            # delete db is there is one
            r.operator_db_id.drop_db()
            if not r.operator_db_id or r.operator_id != r.operator_db_id.operator_id:
                r.operator_db_id = self.env['saas.db'].create({
                    'name': r.operator_db_name,
                    'operator_id': r.operator_id.id,
                    'type': 'template',
                })
            password = random_password()
            self.env['saas.log'].log_db_creating(r.operator_db_id)

            r.write({
                'state': 'creating',
                'password': password,
            })
            r.operator_db_id.with_delay().create_db(
                None,
                r.template_id.template_demo,
                password,
                callback_obj=r,
                callback_method='_on_template_created')

    def _on_template_created(self):
        self.ensure_one()
        self.to_rebuild = False
        self.state = 'installing_modules'
        self.with_delay()._install_modules()

    @job
    def _install_modules(self):
        self.ensure_one()
        domain = safe_eval(self.template_id.template_modules_domain)
        domain = [('name', 'in', MANDATORY_MODULES + domain)]
        if self.operator_id.type == 'local':
            db = sql_db.db_connect(self.operator_db_name)
            with api.Environment.manage(), db.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                module_ids = env['ir.module.module'].search([('state', '=', 'uninstalled')] + domain)
                module_ids.button_immediate_install()
                # Some magic to force reloading registry in other workers
                env.registry.registry_invalidated = True
                env.registry.signal_changes()
        else:
            auth = self._rpc_auth()
            rpc_install_modules(auth, domain)
        self.state = 'post_init'
        self.with_delay()._post_init()

    @job
    def _post_init(self):
        if self.operator_id.type == 'local':
            db = sql_db.db_connect(self.operator_db_name)
            with api.Environment.manage(), db.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                action = env['ir.actions.server'].create({
                    'name': 'Local Code Eval',
                    'state': 'code',
                    'model_id': 1,
                    'code': self.template_id.template_post_init
                })
                action.run()
            self.state = 'done'
        else:
            auth = self._rpc_auth()
            rpc_code_eval(auth, self.template_id.template_post_init)
            self.state = 'done'

    def _rpc_auth(self):
        self.ensure_one()
        url = self.operator_db_id.get_url()
        return rpc_auth(
            url,
            self.operator_db_name,
            admin_username='admin',
            admin_password=self.password)

    @staticmethod
    def _convert_to_dict(key_values):
        key_value_dict = {}
        for r in key_values:
            if r.key:
                key_value_dict.update({r.key: r.value})
        return key_value_dict

    @api.multi
    def create_db(self, db_name, key_values):
        self.ensure_one()
        build = self.env['saas.db'].create({
            'name': db_name,
            'operator_id': self.operator_id.id,
            'type': 'build',
        })

        self.env['saas.log'].log_db_creating(build, self.operator_db_id)

        build.with_delay().create_db(
            self.operator_db_name,
            self.template_id.template_demo,
            self.password,
        )
        key_value_dict = self._convert_to_dict(key_values)
        self.operator_id.with_delay().build_post_init(build, self.template_id.build_post_init, key_value_dict)

        return build
